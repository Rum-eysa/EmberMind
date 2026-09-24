"""Framework-independent FIRMS synchronization use cases."""
from datetime import datetime, timezone

from src.models.fire import FirmsSyncStatus
from src.services.firms import FirmsClient, FirmsSourceError, ingest_firms
from sqlalchemy import select
from sqlalchemy.orm import Session


def sync_firms(session: Session, settings) -> dict[str, int]:
    """Fetch FIRMS data and persist its observations and sync status."""
    status = session.scalar(
        select(FirmsSyncStatus).where(FirmsSyncStatus.source == "NASA FIRMS")
    )
    if status is None:
        status = FirmsSyncStatus(source="NASA FIRMS")
        session.add(status)
    try:
        result = ingest_firms(
            session,
            FirmsClient(
                api_key=settings.FIRMS_API_KEY,
                source=settings.FIRMS_SOURCE,
                bbox=settings.FIRMS_BBOX,
                days=settings.FIRMS_DAYS,
            ),
            settings.FIRMS_CLUSTER_RADIUS_KM,
        )
    except FirmsSourceError as exc:
        status.last_error_at = datetime.now(timezone.utc).replace(tzinfo=None)  # type: ignore[assignment]
        status.last_error = str(exc)[:500]  # type: ignore[assignment]
        raise
    status.last_success_at = datetime.now(timezone.utc).replace(tzinfo=None)  # type: ignore[assignment]
    status.last_error = None  # type: ignore[assignment]
    status.last_observation_count = result["observations"]  # type: ignore[assignment]
    return result


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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    age_minutes = None
    if status.last_success_at:
        age_minutes = round((now - status.last_success_at).total_seconds() / 60, 1)
    return {
        "source": "NASA FIRMS",
        "last_success_at": status.last_success_at.isoformat() + "Z"
        if status.last_success_at
        else None,
        "last_success_age_minutes": age_minutes,
        "last_observation_count": status.last_observation_count,
        "last_error": status.last_error,
        "stale": age_minutes is None or age_minutes > 20,
    }
