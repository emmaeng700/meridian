from uuid import UUID
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.source import SourceType


class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: SourceType
    connection_string: Optional[str] = None
    file_path: Optional[str] = None


class DataSourceUpdate(BaseModel):
    name: Optional[str] = None
    connection_string: Optional[str] = None
    file_path: Optional[str] = None
    is_active: Optional[bool] = None


class DataSourceResponse(BaseModel):
    id: UUID
    name: str
    source_type: SourceType
    connection_string: Optional[str] = None
    file_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    is_active: bool
    latest_health_score: Optional[float] = None
    latest_profiled_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DataSourceList(BaseModel):
    items: list[DataSourceResponse]
    total: int
