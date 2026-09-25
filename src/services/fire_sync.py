"""Framework-independent FIRMS synchronization use cases.

A single sync run now pulls every configured VIIRS/MODIS product, merges the
detections onto the common schema, deduplicates overlapping fires across
satellites, and records the publication latency of each event.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FirmsSyncStatus
from src.services.firms import FirmsSourceError
from src.services.satellite_merge import (
    build_satellite_clients,
    fetch_all_sources,
    merge_and_ingest,
    satellite_coverage_summary,
)
from src.utils.timeutils import to_utc_iso, utc_now


def sync_firms(session: Session, settings) -> dict[str, Any]:
    """Fetch all VIIRS/MODIS products, merge, deduplicate, and persist."""
    status = session.scalar(
        select(FirmsSyncStatus).where(FirmsSyncStatus.source == "NASA FIRMS")
    )
    if status is None:
        status = FirmsSyncStatus(source="NASA FIRMS")
        session.add(status)

    clients = build_satellite_clients(settings)
    detections, failed_sources = fetch_all_sources(clients)
    if not detections:
        message = "All FIRMS satellite products failed to deliver data"
        status.last_error_at = utc_now()  # type: ignore[assignment]
        status.last_error = message[:500]  # type: ignore[assignment]
        raise FirmsSourceError(message)

    merged, result = merge_and_ingest(
        session,
        detections,
        failed_sources=failed_sources,
        radius_km=float(getattr(settings, "FIRMS_CLUSTER_RADIUS_KM", 2.0)),
        time_window_minutes=int(
            getattr(settings, "SATELLITE_DEDUP_TIME_WINDOW_MINUTES", 180)
        ),
    )
    status.last_success_at = utc_now()  # type: ignore[assignment]
    partial_error = (
        f"partial failure: {', '.join(failed_sources)}" if failed_sources else None
    )
    status.last_error = partial_error  # type: ignore[assignment]
    status.last_observation_count = result["observations"]  # type: ignore[assignment]
    return {
        **result,
        "sources": merged.sources,
        "coverage": satellite_coverage_summary(merged),
    }


def sync_status(session: Session) -> dict[str, object]:
    """Return the freshness and error state of the FIRMS source."""
    status = session.scalar(
        select(FirmsSyncStatus).where(FirmsSyncStatus.source == "NASA FIRMS")
    )
    if status is None:
        return {
            "source": "NASA FIRMS",
            "last_success_at": None,
            "last_error": None,
            "stale": True,
        }
    now = utc_now()
    age_minutes = None
    if status.last_success_at:
        age_minutes = round((now - status.last_success_at).total_seconds() / 60, 1)
    return {
        "source": "NASA FIRMS",
        "last_success_at": to_utc_iso(status.last_success_at),
        "last_success_age_minutes": age_minutes,
        "last_observation_count": status.last_observation_count,
        "last_error": status.last_error,
        "stale": age_minutes is None or age_minutes > 20,
    }
