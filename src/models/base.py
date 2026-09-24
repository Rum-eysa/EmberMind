"""Framework-independent SQLAlchemy model base."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer

from src.database import Base


class TimestampMixin:
    """Timestamp columns shared by persisted models."""

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class BaseModel(Base, TimestampMixin):
    """Base model with an integer primary key."""

    __abstract__ = True
    id = Column(Integer, primary_key=True)
