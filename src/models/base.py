"""Framework-independent SQLAlchemy model base."""
from sqlalchemy import Column, DateTime, Integer

from src.database import Base
from src.utils.timeutils import utc_now


class TimestampMixin:
    """Timestamp columns shared by persisted models."""

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class BaseModel(Base, TimestampMixin):
    """Base model with an integer primary key."""

    __abstract__ = True
    id = Column(Integer, primary_key=True)
