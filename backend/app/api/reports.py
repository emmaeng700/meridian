"""Quality report generation endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.source import DataSource
from app.models.profile import TableProfile, ColumnProfile
from app.models.anomaly import Anomaly, Severity

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{source_id}")
async def get_report(source_id: str, db: AsyncSession = Depends(get_db)):
    # Validate source
    src_result = await db.execute(
        select(DataSource).where(DataSource.id == uuid.UUID(source_id))
    )
    source = src_result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    # Fetch all profiles for this source (last 30)
    prof_result = await db.execute(
        select(TableProfile)
        .options(selectinload(TableProfile.column_profiles))
        .where(TableProfile.source_id == source.id)
        .order_by(desc(TableProfile.profiled_at))
        .limit(30)
    )
    profiles = prof_result.scalars().all()

    # Latest profile per table
    latest_by_table: dict[str, TableProfile] = {}
    for p in profiles:
        if p.table_name not in latest_by_table:
            latest_by_table[p.table_name] = p

    # Overall health score = average of latest profiles
    health_scores = [p.health_score for p in latest_by_table.values()]
    overall_health = sum(health_scores) / len(health_scores) if health_scores else 100.0

    # Recent anomalies (last 7 days)
    since = datetime.utcnow() - timedelta(days=7)
    anom_result = await db.execute(
        select(Anomaly)
        .where(Anomaly.source_id == source.id, Anomaly.detected_at >= since)
        .order_by(desc(Anomaly.detected_at))
    )
    recent_anomalies = anom_result.scalars().all()

    # Anomaly breakdown by severity
    by_severity: dict[str, int] = {}
    for a in recent_anomalies:
        sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Anomaly timeline (last 7 days, grouped by day)
    timeline: dict[str, int] = {}
    for a in recent_anomalies:
        day = a.detected_at.strftime("%Y-%m-%d")
        timeline[day] = timeline.get(day, 0) + 1

    # Column quality matrix: per table, per column → {null_rate, distinct_rate, health}
    column_quality_matrix: list[dict[str, Any]] = []
    for table_name, tp in latest_by_table.items():
        for cp in tp.column_profiles:
            column_quality_matrix.append(
                {
                    "table_name": table_name,
                    "column_name": cp.column_name,
                    "data_type": cp.data_type,
                    "null_rate": cp.null_rate,
                    "distinct_rate": cp.distinct_rate,
                    "mean_value": cp.mean_value,
                    "std_value": cp.std_value,
                    "min_value": cp.min_value,
                    "max_value": cp.max_value,
                }
            )

    # Row count trend (all profiles for primary table, ordered asc)
    primary_table = list(latest_by_table.keys())[0] if latest_by_table else None
    row_count_trend: list[dict[str, Any]] = []
    health_trend: list[dict[str, Any]] = []

    if primary_table:
        trend_result = await db.execute(
            select(TableProfile)
            .where(TableProfile.source_id == source.id, TableProfile.table_name == primary_table)
            .order_by(TableProfile.profiled_at)
        )
        trend_profiles = trend_result.scalars().all()
        for tp in trend_profiles:
            row_count_trend.append(
                {"profiled_at": tp.profiled_at.isoformat(), "row_count": tp.row_count}
            )
            health_trend.append(
                {"profiled_at": tp.profiled_at.isoformat(), "health_score": tp.health_score}
            )

    # Anomaly list for display
    anomaly_list = [
        {
            "id": str(a.id),
            "column_name": a.column_name,
            "anomaly_type": a.anomaly_type.value if hasattr(a.anomaly_type, "value") else str(a.anomaly_type),
            "severity": a.severity.value if hasattr(a.severity, "value") else str(a.severity),
            "metric_name": a.metric_name,
            "expected_value": a.expected_value,
            "actual_value": a.actual_value,
            "deviation_score": a.deviation_score,
            "description": a.description,
            "detected_at": a.detected_at.isoformat(),
            "acknowledged": a.acknowledged,
            "detector": a.detector,
        }
        for a in recent_anomalies[:20]
    ]

    return {
        "source_id": source_id,
        "source_name": source.name,
        "source_type": source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type),
        "generated_at": datetime.utcnow().isoformat(),
        "overall_health_score": overall_health,
        "tables_profiled": len(latest_by_table),
        "total_profiles": len(profiles),
        "recent_anomaly_count": len(recent_anomalies),
        "anomaly_breakdown": by_severity,
        "anomaly_timeline": [
            {"date": k, "count": v} for k, v in sorted(timeline.items())
        ],
        "column_quality_matrix": column_quality_matrix,
        "row_count_trend": row_count_trend,
        "health_trend": health_trend,
        "recent_anomalies": anomaly_list,
    }
