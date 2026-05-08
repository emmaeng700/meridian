from uuid import UUID
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.anomaly import AnomalyType, Severity


class AnomalyResponse(BaseModel):
    id: UUID
    source_id: UUID
    table_profile_id: UUID
    column_name: Optional[str] = None
    anomaly_type: AnomalyType
    severity: Severity
    metric_name: str
    expected_value: float
    actual_value: float
    deviation_score: float
    description: str
    detected_at: datetime
    acknowledged: bool
    detector: str

    model_config = {"from_attributes": True}


class AnomalyList(BaseModel):
    items: list[AnomalyResponse]
    total: int


class AnomalySummary(BaseModel):
    total: int
    by_severity: dict[str, int]
    by_type: dict[str, int]
    by_source: dict[str, int]
    unacknowledged: int


class AcknowledgeRequest(BaseModel):
    acknowledged: bool = True
