import uuid
import enum
from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Boolean, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class AnomalyType(str, enum.Enum):
    null_rate_spike = "null_rate_spike"
    volume_drop = "volume_drop"
    schema_drift = "schema_drift"
    distribution_shift = "distribution_shift"
    outlier = "outlier"


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    table_profile_id = Column(UUID(as_uuid=True), ForeignKey("table_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    column_name = Column(String(255), nullable=True)  # null = table-level anomaly

    anomaly_type = Column(SAEnum(AnomalyType), nullable=False, index=True)
    severity = Column(SAEnum(Severity), nullable=False, index=True)

    metric_name = Column(String(255), nullable=False)
    expected_value = Column(Float, nullable=False)
    actual_value = Column(Float, nullable=False)
    deviation_score = Column(Float, nullable=False)
    description = Column(String(2048), nullable=False)

    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    acknowledged = Column(Boolean, default=False, nullable=False, index=True)
    detector = Column(String(100), nullable=False)

    # Relationships
    source = relationship("DataSource", back_populates="anomalies")
    table_profile = relationship("TableProfile", back_populates="anomalies")
