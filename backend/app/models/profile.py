import uuid
from datetime import datetime

from sqlalchemy import Column, String, BigInteger, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class TableProfile(Base):
    __tablename__ = "table_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    table_name = Column(String(255), nullable=False, index=True)
    row_count = Column(BigInteger, nullable=False, default=0)
    column_count = Column(Integer, nullable=False, default=0)
    profiled_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    health_score = Column(Float, default=100.0, nullable=False)

    # Relationships
    source = relationship("DataSource", back_populates="profiles")
    column_profiles = relationship("ColumnProfile", back_populates="table_profile", cascade="all, delete-orphan")
    anomalies = relationship("Anomaly", back_populates="table_profile", cascade="all, delete-orphan")


class ColumnProfile(Base):
    __tablename__ = "column_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_profile_id = Column(UUID(as_uuid=True), ForeignKey("table_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    column_name = Column(String(255), nullable=False)
    data_type = Column(String(100), nullable=False)

    # Nullability
    null_count = Column(BigInteger, default=0, nullable=False)
    null_rate = Column(Float, default=0.0, nullable=False)

    # Cardinality
    distinct_count = Column(BigInteger, default=0, nullable=False)
    distinct_rate = Column(Float, default=0.0, nullable=False)

    # Numeric stats
    min_value = Column(Float, nullable=True)
    max_value = Column(Float, nullable=True)
    mean_value = Column(Float, nullable=True)
    std_value = Column(Float, nullable=True)
    median_value = Column(Float, nullable=True)

    # String stats
    min_length = Column(Float, nullable=True)
    max_length = Column(Float, nullable=True)
    avg_length = Column(Float, nullable=True)

    # Percentiles
    p25 = Column(Float, nullable=True)
    p75 = Column(Float, nullable=True)
    p95 = Column(Float, nullable=True)

    # Sample values
    sample_values = Column(JSON, default=list)

    # Relationships
    table_profile = relationship("TableProfile", back_populates="column_profiles")
