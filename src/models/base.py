"""Framework-independent SQLAlchemy model base."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer

from src.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    """Timestamp columns shared by persisted models."""

    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class BaseModel(Base, TimestampMixin):
    """Base model with an integer primary key."""

    __abstract__ = True
    id = Column(Integer, primary_key=True)
