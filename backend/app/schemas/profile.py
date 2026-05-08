from uuid import UUID
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel


class ColumnProfileResponse(BaseModel):
    id: UUID
    table_profile_id: UUID
    column_name: str
    data_type: str
    null_count: int
    null_rate: float
    distinct_count: int
    distinct_rate: float
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean_value: Optional[float] = None
    std_value: Optional[float] = None
    median_value: Optional[float] = None
    min_length: Optional[float] = None
    max_length: Optional[float] = None
    avg_length: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    p95: Optional[float] = None
    sample_values: list[Any] = []

    model_config = {"from_attributes": True}


class TableProfileResponse(BaseModel):
    id: UUID
    source_id: UUID
    table_name: str
    row_count: int
    column_count: int
    profiled_at: datetime
    health_score: float
    column_profiles: list[ColumnProfileResponse] = []
    anomaly_count: Optional[int] = None

    model_config = {"from_attributes": True}


class TableProfileList(BaseModel):
    items: list[TableProfileResponse]
    total: int


class ProfileRunRequest(BaseModel):
    table_name: Optional[str] = None  # None = profile all tables
