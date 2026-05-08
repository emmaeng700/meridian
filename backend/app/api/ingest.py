"""
Direct row-push ingest endpoint.

POST /ingest/{table_name}
  Body: { "rows": [ {col: val, ...}, ... ] }

Creates (or appends to) a managed table in Meridian's own Postgres,
auto-registers a source if needed, then triggers a full profile + anomaly
detection run — returning the results immediately.

Ideal for demos, CI pipelines, or any situation where you don't have a
separate database to point Meridian at.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.source import DataSource, SourceType
from app.models.profile import TableProfile, ColumnProfile
from app.models.anomaly import Anomaly, AnomalyType, Severity
from app.api.sources import _run_profiler_sync, _run_detectors, _compute_health_score

router = APIRouter(prefix="/ingest", tags=["ingest"])

# The connection string Meridian uses for managed tables (same DB as Meridian itself)
MANAGED_DSN = settings.SYNC_DATABASE_URL


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class IngestPayload(BaseModel):
    rows: list[dict[str, Any]]
    source_name: Optional[str] = None   # optional friendly name for the source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_pg_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "BIGINT"
    if isinstance(value, float):
        return "DOUBLE PRECISION"
    return "TEXT"


def _ensure_table_sync(table_name: str, rows: list[dict[str, Any]]) -> None:
    """
    Create the table if it doesn't exist, then add any missing columns,
    then bulk-insert the new rows. Runs synchronously (called via asyncio.to_thread).
    """
    if not rows:
        return

    conn = psycopg2.connect(MANAGED_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Check if table exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                )
                """,
                (table_name,),
            )
            exists = cur.fetchone()[0]

            if not exists:
                # Build CREATE TABLE from first row
                col_defs = ", ".join(
                    f'"{col}" {_infer_pg_type(val)}'
                    for col, val in rows[0].items()
                )
                cur.execute(
                    f'CREATE TABLE IF NOT EXISTS "{table_name}" '
                    f"(id SERIAL PRIMARY KEY, _ingested_at TIMESTAMP DEFAULT now(), {col_defs})"
                )
            else:
                # Add any new columns that appeared in this batch
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table_name,),
                )
                existing_cols = {r[0] for r in cur.fetchall()}
                for col, val in rows[0].items():
                    if col not in existing_cols:
                        pg_type = _infer_pg_type(val)
                        cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {pg_type}')

            # Bulk insert
            all_cols = list(rows[0].keys())
            col_str = ", ".join(f'"{c}"' for c in all_cols)
            placeholders = ", ".join(["%s"] * len(all_cols))

            records = [
                tuple(row.get(c) for c in all_cols)
                for row in rows
            ]
            psycopg2.extras.execute_batch(
                cur,
                f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})',
                records,
                page_size=500,
            )
    finally:
        conn.close()


async def _get_or_create_source(
    table_name: str,
    source_name: Optional[str],
    db: AsyncSession,
) -> DataSource:
    """Return existing managed source for this table or create one."""
    managed_name = source_name or f"Managed: {table_name}"

    result = await db.execute(
        select(DataSource).where(
            DataSource.name == managed_name,
            DataSource.is_active == True,
        )
    )
    source = result.scalar_one_or_none()
    if source:
        return source

    source = DataSource(
        id=uuid.uuid4(),
        name=managed_name,
        source_type=SourceType.postgres,
        connection_string=MANAGED_DSN,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_active=True,
    )
    db.add(source)
    await db.flush()
    return source


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/{table_name}", status_code=status.HTTP_200_OK)
async def ingest_rows(
    table_name: str,
    payload: IngestPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Push rows directly into Meridian and get anomaly results back immediately.

    - Creates the table on first call (columns inferred from the first row).
    - Adds missing columns automatically on subsequent calls.
    - Registers a source automatically — no manual setup needed.
    - Returns a full profile + detected anomalies in one shot.

    Example:
    ```
    POST /api/v1/ingest/sales_data
    {
      "rows": [
        {"revenue": 1200.5, "region": "US", "date": "2024-01-01"},
        {"revenue": null,   "region": "EU", "date": "2024-01-02"}
      ]
    }
    ```
    """
    if not payload.rows:
        raise HTTPException(status_code=422, detail="rows must not be empty")

    # Sanitize table name (alphanumeric + underscores only)
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in table_name)
    if not safe_name:
        raise HTTPException(status_code=422, detail="Invalid table name")

    # 1 — Write rows to Postgres (sync, in thread)
    await asyncio.to_thread(_ensure_table_sync, safe_name, payload.rows)

    # 2 — Get or create source
    source = await _get_or_create_source(safe_name, payload.source_name, db)

    # 3 — Profile the table
    from app.models.profile import TableProfile, ColumnProfile
    from sqlalchemy.orm import selectinload

    raw_profiles: list[dict[str, Any]] = await asyncio.to_thread(
        _run_profiler_sync, source, safe_name
    )

    if not raw_profiles:
        raise HTTPException(status_code=500, detail="Profiler returned no results")

    raw = raw_profiles[0]

    # 4 — Fetch historical profiles for anomaly detection
    hist_result = await db.execute(
        select(TableProfile)
        .options(selectinload(TableProfile.column_profiles))
        .where(TableProfile.source_id == source.id, TableProfile.table_name == safe_name)
        .order_by(TableProfile.profiled_at)
    )
    historical_orm = hist_result.scalars().all()

    historical_raw: list[dict[str, Any]] = [
        {
            "table_name": hp.table_name,
            "row_count": hp.row_count,
            "column_count": hp.column_count,
            "columns": [
                {
                    "column_name": cp.column_name,
                    "data_type": cp.data_type,
                    "null_count": cp.null_count,
                    "null_rate": cp.null_rate,
                    "distinct_count": cp.distinct_count,
                    "distinct_rate": cp.distinct_rate,
                    "min_value": cp.min_value,
                    "max_value": cp.max_value,
                    "mean_value": cp.mean_value,
                    "std_value": cp.std_value,
                    "median_value": cp.median_value,
                    "p25": cp.p25,
                    "p75": cp.p75,
                    "p95": cp.p95,
                }
                for cp in hp.column_profiles
            ],
        }
        for hp in historical_orm
    ]

    # 5 — Persist new TableProfile
    table_profile = TableProfile(
        id=uuid.uuid4(),
        source_id=source.id,
        table_name=safe_name,
        row_count=raw["row_count"],
        column_count=raw["column_count"],
        profiled_at=datetime.utcnow(),
        health_score=100.0,
    )
    db.add(table_profile)
    await db.flush()

    # 6 — Persist ColumnProfiles
    for col in raw.get("columns", []):
        cp = ColumnProfile(
            id=uuid.uuid4(),
            table_profile_id=table_profile.id,
            column_name=col["column_name"],
            data_type=col["data_type"],
            null_count=col.get("null_count", 0),
            null_rate=col.get("null_rate", 0.0),
            distinct_count=col.get("distinct_count", 0),
            distinct_rate=col.get("distinct_rate", 0.0),
            min_value=col.get("min_value"),
            max_value=col.get("max_value"),
            mean_value=col.get("mean_value"),
            std_value=col.get("std_value"),
            median_value=col.get("median_value"),
            min_length=col.get("min_length"),
            max_length=col.get("max_length"),
            avg_length=col.get("avg_length"),
            p25=col.get("p25"),
            p75=col.get("p75"),
            p95=col.get("p95"),
            sample_values=col.get("sample_values", []),
        )
        db.add(cp)
    await db.flush()

    # 7 — Run detectors
    tp_id = str(table_profile.id)
    src_id = str(source.id)
    detected = await asyncio.to_thread(
        _run_detectors, raw, historical_raw, src_id, tp_id
    )

    # 8 — Persist anomalies
    for a in detected:
        anomaly = Anomaly(
            id=uuid.UUID(a["id"]),
            source_id=uuid.UUID(a["source_id"]),
            table_profile_id=uuid.UUID(a["table_profile_id"]),
            column_name=a.get("column_name"),
            anomaly_type=AnomalyType(a["anomaly_type"]),
            severity=Severity(a["severity"]),
            metric_name=a["metric_name"],
            expected_value=float(a["expected_value"]) if not isinstance(a["expected_value"], str) else 0.0,
            actual_value=float(a["actual_value"]) if not isinstance(a["actual_value"], str) else 1.0,
            deviation_score=float(a["deviation_score"]),
            description=a["description"],
            detected_at=datetime.utcnow(),
            acknowledged=False,
            detector=a["detector"],
        )
        db.add(anomaly)
    await db.flush()

    # 9 — Compute health score
    health_score = _compute_health_score(detected)
    table_profile.health_score = health_score

    return {
        "table_name": safe_name,
        "source_id": str(source.id),
        "profile_id": str(table_profile.id),
        "rows_ingested": len(payload.rows),
        "total_rows": raw["row_count"],
        "column_count": raw["column_count"],
        "health_score": health_score,
        "anomaly_count": len(detected),
        "anomalies": [
            {
                "column": a.get("column_name"),
                "type": a["anomaly_type"],
                "severity": a["severity"],
                "metric": a["metric_name"],
                "description": a["description"],
            }
            for a in detected
        ],
    }
