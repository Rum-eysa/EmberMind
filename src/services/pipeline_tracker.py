"""Pipeline job tracking and status monitoring service."""
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.models.pipeline import PipelineJobHistory


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_job_id(job_or_id: PipelineJobHistory | int) -> int:
    if isinstance(job_or_id, int):
        return job_or_id
    return cast(int, job_or_id.id)


class PipelineTracker:
    """Service to track, record, and query pipeline execution history."""

    @staticmethod
    def start_job(session: Session, job_name: str, source: str) -> PipelineJobHistory:
        """Create and persist a new job run entry in RUNNING state."""
        job = PipelineJobHistory(
            job_name=job_name,
            source=source,
            status="RUNNING",
            start_time=_utc_now(),
            attempt_count=1,
            records_processed=0,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    @staticmethod
    def complete_job(
        session: Session,
        job_or_id: PipelineJobHistory | int,
        records_processed: int = 0,
        attempt_count: int = 1,
    ) -> PipelineJobHistory:
        """Mark job run as SUCCESS."""
        job_id = _resolve_job_id(job_or_id)
        job = session.get(PipelineJobHistory, job_id)
        if not job:
            raise ValueError(f"Job with id {job_id} not found.")

        now = _utc_now()
        start_time = cast(datetime | None, job.start_time)
        duration_seconds = (
            round((now - start_time).total_seconds(), 3) if start_time else None
        )
        session.execute(
            update(PipelineJobHistory)
            .where(PipelineJobHistory.id == job_id)
            .values(
                status="SUCCESS",
                end_time=now,
                duration_seconds=duration_seconds,
                records_processed=records_processed,
                attempt_count=attempt_count,
            )
        )
        session.commit()
        updated = session.get(PipelineJobHistory, job_id)
        if not updated:
            raise ValueError(f"Job with id {job_id} not found.")
        return updated

    @staticmethod
    def fail_job(
        session: Session,
        job_or_id: PipelineJobHistory | int,
        error_message: str,
        attempt_count: int = 1,
    ) -> PipelineJobHistory:
        """Mark job run as FAILED."""
        job_id = _resolve_job_id(job_or_id)
        job = session.get(PipelineJobHistory, job_id)
        if not job:
            raise ValueError(f"Job with id {job_id} not found.")

        now = _utc_now()
        start_time = cast(datetime | None, job.start_time)
        duration_seconds = (
            round((now - start_time).total_seconds(), 3) if start_time else None
        )
        session.execute(
            update(PipelineJobHistory)
            .where(PipelineJobHistory.id == job_id)
            .values(
                status="FAILED",
                end_time=now,
                duration_seconds=duration_seconds,
                error_message=error_message,
                attempt_count=attempt_count,
            )
        )
        session.commit()
        updated = session.get(PipelineJobHistory, job_id)
        if not updated:
            raise ValueError(f"Job with id {job_id} not found.")
        return updated

    @staticmethod
    def get_job_history(
        session: Session,
        job_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve recent pipeline job execution history."""
        query = select(PipelineJobHistory)
        if job_name:
            query = query.where(PipelineJobHistory.job_name == job_name)
        rows = session.scalars(
            query.order_by(PipelineJobHistory.start_time.desc()).limit(limit)
        ).all()
        return [row.as_dict for row in rows]

    @staticmethod
    def get_pipeline_summary(session: Session) -> dict[str, Any]:
        """Summarize pipeline status across all sources and total metrics."""
        sources = ["FIRMS", "OpenWeather", "USGS/SRTM", "Copernicus", "OpenStreetMap"]
        source_summary: dict[str, Any] = {}

        for src in sources:
            last_job = session.scalars(
                select(PipelineJobHistory)
                .where(PipelineJobHistory.source == src)
                .order_by(PipelineJobHistory.start_time.desc())
                .limit(1)
            ).first()

            total_runs = (
                session.scalar(
                    select(func.count())
                    .select_from(PipelineJobHistory)
                    .where(PipelineJobHistory.source == src)
                )
                or 0
            )

            successful_runs = (
                session.scalar(
                    select(func.count())
                    .select_from(PipelineJobHistory)
                    .where(
                        PipelineJobHistory.source == src,
                        PipelineJobHistory.status == "SUCCESS",
                    )
                )
                or 0
            )

            source_summary[src] = {
                "last_run": last_job.as_dict if last_job else None,
                "total_runs": total_runs,
                "successful_runs": successful_runs,
                "success_rate": round(successful_runs / total_runs, 2)
                if total_runs > 0
                else 1.0,
            }

        total_jobs = (
            session.scalar(select(func.count()).select_from(PipelineJobHistory)) or 0
        )

        return {
            "status": "healthy",
            "total_job_runs": total_jobs,
            "sources": source_summary,
        }
