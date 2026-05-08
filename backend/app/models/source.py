import uuid
import enum
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SourceType(str, enum.Enum):
    postgres = "postgres"
    csv = "csv"
    parquet = "parquet"


class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True, index=True)
    source_type = Column(SAEnum(SourceType), nullable=False)
    connection_string = Column(String(1024), nullable=True)
    file_path = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    profiles = relationship("TableProfile", back_populates="source", cascade="all, delete-orphan")
    anomalies = relationship("Anomaly", back_populates="source", cascade="all, delete-orphan")
