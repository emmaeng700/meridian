"""Profile history and detail endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.profile import TableProfile, ColumnProfile
from app.models.anomaly import Anomaly
from app.schemas.profile import TableProfileResponse, TableProfileList, ColumnProfileResponse

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=TableProfileList)
async def list_profiles(
    source_id: Optional[str] = Query(None),
    table_name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(TableProfile)
        .options(selectinload(TableProfile.column_profiles))
        .order_by(desc(TableProfile.profiled_at))
    )

    if source_id:
        query = query.where(TableProfile.source_id == uuid.UUID(source_id))
    if table_name:
        query = query.where(TableProfile.table_name == table_name)

    total_result = await db.execute(query)
    all_items = total_result.scalars().all()
    total = len(all_items)

    paginated = all_items[offset : offset + limit]

    items = []
    for tp in paginated:
        # Get anomaly count for this profile
        anom_result = await db.execute(
            select(Anomaly).where(Anomaly.table_profile_id == tp.id)
        )
        anom_count = len(anom_result.scalars().all())

        col_profiles = [
            ColumnProfileResponse.model_validate(cp) for cp in tp.column_profiles
        ]
        items.append(
            TableProfileResponse(
                id=tp.id,
                source_id=tp.source_id,
                table_name=tp.table_name,
                row_count=tp.row_count,
                column_count=tp.column_count,
                profiled_at=tp.profiled_at,
                health_score=tp.health_score,
                column_profiles=col_profiles,
                anomaly_count=anom_count,
            )
        )

    return TableProfileList(items=items, total=total)


@router.get("/{profile_id}", response_model=TableProfileResponse)
async def get_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TableProfile)
        .options(selectinload(TableProfile.column_profiles))
        .where(TableProfile.id == uuid.UUID(profile_id))
    )
    tp = result.scalar_one_or_none()
    if tp is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    anom_result = await db.execute(
        select(Anomaly).where(Anomaly.table_profile_id == tp.id)
    )
    anom_count = len(anom_result.scalars().all())

    col_profiles = [ColumnProfileResponse.model_validate(cp) for cp in tp.column_profiles]

    return TableProfileResponse(
        id=tp.id,
        source_id=tp.source_id,
        table_name=tp.table_name,
        row_count=tp.row_count,
        column_count=tp.column_count,
        profiled_at=tp.profiled_at,
        health_score=tp.health_score,
        column_profiles=col_profiles,
        anomaly_count=anom_count,
    )
