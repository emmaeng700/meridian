"""Anomaly listing, acknowledgement, and summary endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.anomaly import Anomaly, AnomalyType, Severity
from app.models.source import DataSource
from app.schemas.anomaly import AnomalyResponse, AnomalyList, AnomalySummary, AcknowledgeRequest

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("/summary", response_model=AnomalySummary)
async def anomaly_summary(
    source_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Anomaly)
    if source_id:
        query = query.where(Anomaly.source_id == uuid.UUID(source_id))

    result = await db.execute(query)
    all_anomalies = result.scalars().all()

    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    unacknowledged = 0

    # Collect source names for display
    source_names: dict[str, str] = {}

    for a in all_anomalies:
        sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
        atype = a.anomaly_type.value if hasattr(a.anomaly_type, "value") else str(a.anomaly_type)
        src_id = str(a.source_id)

        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_type[atype] = by_type.get(atype, 0) + 1

        if src_id not in source_names:
            src_result = await db.execute(select(DataSource).where(DataSource.id == a.source_id))
            src = src_result.scalar_one_or_none()
            source_names[src_id] = src.name if src else src_id

        name = source_names[src_id]
        by_source[name] = by_source.get(name, 0) + 1

        if not a.acknowledged:
            unacknowledged += 1

    return AnomalySummary(
        total=len(all_anomalies),
        by_severity=by_severity,
        by_type=by_type,
        by_source=by_source,
        unacknowledged=unacknowledged,
    )


@router.get("", response_model=AnomalyList)
async def list_anomalies(
    source_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    anomaly_type: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Anomaly).order_by(desc(Anomaly.detected_at))

    if source_id:
        query = query.where(Anomaly.source_id == uuid.UUID(source_id))
    if severity:
        query = query.where(Anomaly.severity == Severity(severity))
    if anomaly_type:
        query = query.where(Anomaly.anomaly_type == AnomalyType(anomaly_type))
    if acknowledged is not None:
        query = query.where(Anomaly.acknowledged == acknowledged)

    result = await db.execute(query)
    all_items = result.scalars().all()
    total = len(all_items)
    paginated = all_items[offset : offset + limit]

    return AnomalyList(
        items=[AnomalyResponse.model_validate(a) for a in paginated],
        total=total,
    )


@router.patch("/{anomaly_id}/acknowledge", response_model=AnomalyResponse)
async def acknowledge_anomaly(
    anomaly_id: str,
    payload: AcknowledgeRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Anomaly).where(Anomaly.id == uuid.UUID(anomaly_id))
    )
    anomaly = result.scalar_one_or_none()
    if anomaly is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    anomaly.acknowledged = payload.acknowledged
    await db.flush()
    await db.refresh(anomaly)
    return AnomalyResponse.model_validate(anomaly)
