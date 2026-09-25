"""Data quality and freshness monitoring across all ingestion sources.

The monitor derives each source's "last successful pull" time and health from
the canonical pipeline job history written by the scheduler (Celery beat and
``/api/v1/pipeline/trigger``). A source is flagged with an operator-visible
warning when it has not delivered fresh data for longer than its configured
freshness threshold.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.pipeline import PipelineJobHistory
from src.utils.timeutils import to_utc_iso, utc_now

RECENT_JOBS_WINDOW = 50


@dataclass(frozen=True)
class SourceSpec:
    """Static description of a monitored data source and its sync cadence."""

    key: str
    job_source: str
    display_name: str
    interval_minutes: int


@dataclass(frozen=True)
class _Signals:
    """Aggregated pipeline job signals extracted for a single source."""

    total: int
    last_success: PipelineJobHistory | None
    consecutive_failures: int
    last_error: str | None
    oldest_attempt: datetime | None
    last_run_status: str | None
    last_run_at: datetime | None


@dataclass(frozen=True)
class _Verdict:
    """Freshness classification for a single source."""

    status: str
    health: str
    age_minutes: float | None
    outage_minutes: float | None
    warning: bool
    warning_message: str | None


def build_source_registry(settings: Any) -> list[SourceSpec]:
    """Return the monitored data sources with their configured sync cadence."""
    return [
        SourceSpec(
            "firms",
            "FIRMS",
            "NASA FIRMS",
            int(settings.FIRMS_SYNC_INTERVAL_MINUTES),
        ),
        SourceSpec(
            "weather",
            "OpenWeather",
            "OpenWeather Forecast",
            int(settings.WEATHER_SYNC_INTERVAL_MINUTES),
        ),
        SourceSpec(
            "topography",
            "USGS/SRTM",
            "USGS/SRTM Topography",
            int(settings.TOPOGRAPHY_SYNC_INTERVAL_MINUTES),
        ),
        SourceSpec(
            "land_cover",
            "Copernicus",
            "Copernicus Land Cover",
            int(settings.LAND_COVER_SYNC_INTERVAL_MINUTES),
        ),
        SourceSpec(
            "road_network",
            "OpenStreetMap",
            "OpenStreetMap Roads",
            int(settings.ROAD_NETWORK_SYNC_INTERVAL_MINUTES),
        ),
    ]


def _recent_jobs(session: Session, job_source: str) -> list[PipelineJobHistory]:
    rows = session.scalars(
        select(PipelineJobHistory)
        .where(PipelineJobHistory.source == job_source)
        .order_by(PipelineJobHistory.start_time.desc())
        .limit(RECENT_JOBS_WINDOW)
    ).all()
    return list(rows)


def _collect_signals(jobs: list[PipelineJobHistory]) -> _Signals:
    """Summarise last success, trailing failures and last run from recent jobs."""
    last_success = next(
        (job for job in jobs if cast(str, job.status) == "SUCCESS"), None
    )
    consecutive = 0
    last_error = None
    for job in jobs:
        status = cast(str, job.status)
        if status == "RUNNING":
            continue
        if status != "FAILED":
            break
        consecutive += 1
        if last_error is None:
            last_error = cast("str | None", job.error_message)
    oldest = cast("datetime | None", jobs[-1].start_time) if jobs else None
    last_run_status = cast("str | None", jobs[0].status) if jobs else None
    last_run_at = cast("datetime | None", jobs[0].start_time) if jobs else None
    return _Signals(
        len(jobs),
        last_success,
        consecutive,
        last_error,
        oldest,
        last_run_status,
        last_run_at,
    )


def _age_minutes(ref: datetime | None, now: datetime) -> float | None:
    if ref is None:
        return None
    return round((now - ref).total_seconds() / 60, 1)


def _success_time(job: PipelineJobHistory | None) -> datetime | None:
    if job is None:
        return None
    end = cast("datetime | None", job.end_time)
    return end if end is not None else cast(datetime, job.start_time)


def _classify(
    spec: SourceSpec,
    signals: _Signals,
    threshold: float,
    failure_threshold: int,
    now: datetime,
) -> _Verdict:
    """Derive freshness status, health and any operator warning for a source."""
    age = _age_minutes(_success_time(signals.last_success), now)
    if signals.total == 0:
        return _Verdict("unknown", "unknown", None, None, False, None)

    outage = age if age is not None else _age_minutes(signals.oldest_attempt, now)

    if signals.last_success is None:
        status = "never_synced"
    elif age is not None and age > threshold:
        status = "stale"
    else:
        status = "fresh"

    failing = signals.consecutive_failures >= failure_threshold
    if failing and status in ("never_synced", "stale"):
        health = "down"
    elif status == "never_synced":
        health = "degraded"
    elif failing or status == "stale":
        health = "degraded"
    else:
        health = "ok"

    warning = False
    message = None
    if health == "down":
        warning = True
        message = (
            f"{spec.display_name} is DOWN: no fresh data for "
            f"{outage:.0f} min (threshold {threshold:.0f} min)."
        )
    elif status == "never_synced":
        warning = True
        message = (
            f"{spec.display_name} has no successful data pull yet "
            f"({outage:.0f} min since first attempt)."
        )
    elif status == "stale":
        warning = True
        message = (
            f"{spec.display_name} data is stale: last successful pull was "
            f"{age:.0f} min ago (threshold {threshold:.0f} min)."
        )

    return _Verdict(status, health, age, outage, warning, message)


def _source_report(
    spec: SourceSpec, threshold: float, signals: _Signals, verdict: _Verdict
) -> dict[str, Any]:
    return {
        "source": spec.key,
        "display_name": spec.display_name,
        "job_source": spec.job_source,
        "sync_interval_minutes": spec.interval_minutes,
        "freshness_threshold_minutes": threshold,
        "last_success_at": to_utc_iso(_success_time(signals.last_success)),
        "last_success_age_minutes": verdict.age_minutes,
        "outage_minutes": verdict.outage_minutes,
        "last_run_status": signals.last_run_status,
        "last_run_at": to_utc_iso(signals.last_run_at),
        "consecutive_failures": signals.consecutive_failures,
        "last_error": signals.last_error,
        "status": verdict.status,
        "health": verdict.health,
        "warning": verdict.warning,
        "warning_message": verdict.warning_message,
    }


def _evaluate_source(
    session: Session, spec: SourceSpec, settings: Any, now: datetime
) -> dict[str, Any]:
    jobs = _recent_jobs(session, spec.job_source)
    signals = _collect_signals(jobs)
    threshold = round(
        spec.interval_minutes * float(settings.DATA_QUALITY_STALE_MULTIPLIER), 1
    )
    verdict = _classify(
        spec,
        signals,
        threshold,
        int(settings.DATA_QUALITY_FAILURE_WARNING_THRESHOLD),
        now,
    )
    return _source_report(spec, threshold, signals, verdict)


def _warning_entry(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source["source"],
        "display_name": source["display_name"],
        "severity": "critical" if source["health"] == "down" else "warning",
        "status": source["status"],
        "health": source["health"],
        "message": source["warning_message"],
        "last_success_at": source["last_success_at"],
        "outage_minutes": source["outage_minutes"],
    }


def _overall_status(
    sources: list[dict[str, Any]], warnings: list[dict[str, Any]]
) -> str:
    if any(source["health"] == "down" for source in sources):
        return "critical"
    if warnings:
        return "degraded"
    return "ok"


def evaluate_data_quality(
    session: Session, settings: Any, now: datetime | None = None
) -> dict[str, Any]:
    """Build a freshness and health report for every monitored data source."""
    reference = now or utc_now()
    sources = [
        _evaluate_source(session, spec, settings, reference)
        for spec in build_source_registry(settings)
    ]
    warnings = [_warning_entry(source) for source in sources if source["warning"]]
    return {
        "generated_at": to_utc_iso(reference),
        "overall_status": _overall_status(sources, warnings),
        "warning_count": len(warnings),
        "sources": sources,
        "warnings": warnings,
    }


def get_data_quality_warnings(
    session: Session, settings: Any, now: datetime | None = None
) -> dict[str, Any]:
    """Return only the operator-visible data quality warnings."""
    report = evaluate_data_quality(session, settings, now)
    return {
        "generated_at": report["generated_at"],
        "overall_status": report["overall_status"],
        "count": report["warning_count"],
        "warnings": report["warnings"],
    }
