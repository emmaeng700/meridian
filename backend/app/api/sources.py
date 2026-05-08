"""CRUD API for DataSource resources and profile triggering."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.source import DataSource, SourceType
from app.models.profile import TableProfile, ColumnProfile
from app.models.anomaly import Anomaly, AnomalyType, Severity
from app.schemas.source import DataSourceCreate, DataSourceResponse, DataSourceList
from app.schemas.profile import TableProfileResponse

router = APIRouter(prefix="/sources", tags=["sources"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_source_or_404(source_id: str, db: AsyncSession) -> DataSource:
    result = await db.execute(select(DataSource).where(DataSource.id == uuid.UUID(source_id)))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Data source not found")
    return source


async def _enrich_source(source: DataSource, db: AsyncSession) -> dict[str, Any]:
    """Add latest_health_score and latest_profiled_at to source dict."""
    result = await db.execute(
        select(TableProfile)
        .where(TableProfile.source_id == source.id)
        .order_by(desc(TableProfile.profiled_at))
        .limit(1)
    )
    latest = result.scalar_one_or_none()

    d = {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "connection_string": source.connection_string,
        "file_path": source.file_path,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "is_active": source.is_active,
        "latest_health_score": latest.health_score if latest else None,
        "latest_profiled_at": latest.profiled_at if latest else None,
    }
    return d


def _compute_health_score(anomalies: list[dict[str, Any]]) -> float:
    critical = sum(1 for a in anomalies if a.get("severity") == "critical")
    high = sum(1 for a in anomalies if a.get("severity") == "high")
    medium = sum(1 for a in anomalies if a.get("severity") == "medium")
    score = 100.0 - critical * 25 - high * 10 - medium * 5
    return max(0.0, score)


# ---------------------------------------------------------------------------
# Profile runner (sync, run in thread)
# ---------------------------------------------------------------------------

def _run_profiler_sync(source: DataSource, table_name: Optional[str]) -> list[dict[str, Any]]:
    """Run the appropriate profiler synchronously (called via asyncio.to_thread)."""
    from app.profiler.postgres import PostgresProfiler
    from app.profiler.csv_profiler import CSVProfiler

    if source.source_type == SourceType.postgres:
        profiler = PostgresProfiler(source.connection_string)
        try:
            if table_name:
                return [profiler.profile_table(table_name)]
            return profiler.profile_all()
        finally:
            profiler.close()
    else:
        profiler = CSVProfiler(source.file_path)
        tables = profiler.list_tables()
        if table_name and table_name in tables:
            return [profiler.profile_table(table_name)]
        return profiler.profile_all()


def _run_detectors(
    current_raw: dict[str, Any],
    historical_raw: list[dict[str, Any]],
    source_id: str,
    table_profile_id: str,
) -> list[dict[str, Any]]:
    from app.detectors.statistical import ZScoreDetector, IQRDetector
    from app.detectors.isolation_forest import IsolationForestDetector
    from app.detectors.schema_drift import SchemaDriftDetector

    anomalies: list[dict[str, Any]] = []

    z = ZScoreDetector(threshold=3.0)
    anomalies.extend(z.detect(current_raw, historical_raw, source_id, table_profile_id))

    iqr = IQRDetector(multiplier=1.5)
    anomalies.extend(iqr.detect(current_raw, historical_raw, source_id, table_profile_id))

    iso = IsolationForestDetector()
    anomalies.extend(iso.detect(current_raw, historical_raw, source_id, table_profile_id))

    previous = historical_raw[-1] if historical_raw else None
    schema = SchemaDriftDetector()
    anomalies.extend(schema.detect(current_raw, previous, source_id, table_profile_id))

    return anomalies


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=DataSourceList)
async def list_sources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DataSource).where(DataSource.is_active == True).order_by(DataSource.created_at)
    )
    sources = result.scalars().all()
    items = [DataSourceResponse(**await _enrich_source(s, db)) for s in sources]
    return DataSourceList(items=items, total=len(items))


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(payload: DataSourceCreate, db: AsyncSession = Depends(get_db)):
    # Validate: postgres needs connection_string, file sources need file_path
    if payload.source_type == SourceType.postgres and not payload.connection_string:
        raise HTTPException(status_code=422, detail="connection_string required for postgres sources")
    if payload.source_type in (SourceType.csv, SourceType.parquet) and not payload.file_path:
        raise HTTPException(status_code=422, detail="file_path required for csv/parquet sources")

    source = DataSource(
        id=uuid.uuid4(),
        name=payload.name,
        source_type=payload.source_type,
        connection_string=payload.connection_string,
        file_path=payload.file_path,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_active=True,
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)
    return DataSourceResponse(**await _enrich_source(source, db))


@router.get("/{source_id}", response_model=DataSourceResponse)
async def get_source(source_id: str, db: AsyncSession = Depends(get_db)):
    source = await _get_source_or_404(source_id, db)
    return DataSourceResponse(**await _enrich_source(source, db))


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)):
    source = await _get_source_or_404(source_id, db)
    source.is_active = False
    source.updated_at = datetime.utcnow()
    await db.flush()


@router.get("/{source_id}/tables")
async def list_tables(source_id: str, db: AsyncSession = Depends(get_db)):
    source = await _get_source_or_404(source_id, db)

    def _list():
        from app.profiler.postgres import PostgresProfiler
        from app.profiler.csv_profiler import CSVProfiler

        if source.source_type == SourceType.postgres:
            p = PostgresProfiler(source.connection_string)
            try:
                return p.list_tables()
            finally:
                p.close()
        else:
            return CSVProfiler(source.file_path).list_tables()

    tables = await asyncio.to_thread(_list)
    return {"tables": tables}


@router.post("/{source_id}/profile")
async def trigger_profile(
    source_id: str,
    table_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    source = await _get_source_or_404(source_id, db)

    # Run profiler in thread pool
    raw_profiles: list[dict[str, Any]] = await asyncio.to_thread(
        _run_profiler_sync, source, table_name
    )

    results = []

    for raw in raw_profiles:
        t_name = raw["table_name"]

        # --- Fetch historical profiles for this table (raw dicts) ---
        hist_result = await db.execute(
            select(TableProfile)
            .options(selectinload(TableProfile.column_profiles))
            .where(TableProfile.source_id == source.id, TableProfile.table_name == t_name)
            .order_by(TableProfile.profiled_at)
        )
        historical_orm = hist_result.scalars().all()

        historical_raw: list[dict[str, Any]] = []
        for hp in historical_orm:
            historical_raw.append(
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
            )

        # --- Save new TableProfile ---
        table_profile = TableProfile(
            id=uuid.uuid4(),
            source_id=source.id,
            table_name=t_name,
            row_count=raw["row_count"],
            column_count=raw["column_count"],
            profiled_at=datetime.utcnow(),
            health_score=100.0,
        )
        db.add(table_profile)
        await db.flush()

        # --- Save ColumnProfiles ---
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

        # --- Run detectors in thread ---
        tp_id = str(table_profile.id)
        src_id = str(source.id)

        detected = await asyncio.to_thread(
            _run_detectors, raw, historical_raw, src_id, tp_id
        )

        # --- Save anomalies ---
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

        # --- Compute health score ---
        health_score = _compute_health_score(detected)
        table_profile.health_score = health_score

        results.append(
            {
                "table_name": t_name,
                "profile_id": str(table_profile.id),
                "row_count": raw["row_count"],
                "column_count": raw["column_count"],
                "health_score": health_score,
                "anomaly_count": len(detected),
            }
        )

    return {"profiles": results, "total": len(results)}
