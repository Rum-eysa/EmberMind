"""Pipeline job history ORM model."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from src.models.base import BaseModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PipelineJobHistory(BaseModel):
    """Tracks history and execution status of pipeline sync jobs."""

    __tablename__ = "pipeline_job_history"

    job_name = Column(String(100), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    start_time = Column(DateTime, default=_utc_now, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=1)
    records_processed = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Convert job history entry to dictionary representation."""
        return {
            "id": self.id,
            "job_name": self.job_name,
            "source": self.source,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "attempt_count": self.attempt_count,
            "records_processed": self.records_processed,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
