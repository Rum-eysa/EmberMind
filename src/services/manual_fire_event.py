"""Manual fire event creation service with deduplication and prediction triggering."""
from datetime import datetime
from math import cos
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster
from src.models.spatial import FireEvent
from src.services.spread_trigger import run_spread_forecast
from src.utils.timeutils import utc_now


class ManualFireEventError(Exception):
    """Exception raised for manual fire event creation errors."""

    pass


class DuplicateFireEventError(ManualFireEventError):
    """Exception raised when a manual event duplicates an existing satellite detection."""

    pass


def generate_event_key(latitude: float, longitude: float, timestamp: datetime) -> str:
    """Generate a unique event key from coordinates and timestamp."""
    lat_str = f"{latitude:.4f}".replace(".", "").replace("-", "m")
    lon_str = f"{longitude:.4f}".replace(".", "").replace("-", "m")
    time_str = timestamp.strftime("%Y%m%d%H%M%S")
    return f"manual_{lat_str}_{lon_str}_{time_str}"


def check_for_duplicates(
    session: Session,
    latitude: float,
    longitude: float,
    distance_threshold_km: float = 5.0,
    time_threshold_hours: float = 24.0,
) -> Optional[FireCluster]:
    """
    Check if the manual event location/time duplicates existing satellite detections.

    Args:
        session: Database session
        latitude: Event latitude
        longitude: Event longitude
        distance_threshold_km: Maximum distance in km to consider as duplicate
        time_threshold_hours: Maximum time difference in hours to consider as duplicate

    Returns:
        Duplicate FireCluster if found, None otherwise
    """
    # Simple bounding box query for performance
    lat_delta = distance_threshold_km / 111.0  # Approximate km to degrees
    lon_delta = distance_threshold_km / (
        111.0 * abs(cos(latitude)) if latitude != 0 else 111.0
    )

    clusters = session.scalars(
        select(FireCluster).where(
            FireCluster.latitude >= latitude - lat_delta,
            FireCluster.latitude <= latitude + lat_delta,
            FireCluster.longitude >= longitude - lon_delta,
            FireCluster.longitude <= longitude + lon_delta,
        )
    ).all()

    now = utc_now()

    for cluster in clusters:
        # Calculate distance using Haversine formula approximation
        cluster_lat = float(cluster.latitude)  # type: ignore[arg-type]
        cluster_lon = float(cluster.longitude)  # type: ignore[arg-type]
        lat_diff = (cluster_lat - latitude) * 111.0
        lon_diff = (
            (cluster_lon - longitude) * 111.0 * abs(cos(latitude))
            if latitude != 0
            else 0
        )
        distance_km = (lat_diff**2 + lon_diff**2) ** 0.5

        # Check time threshold
        time_diff_hours = abs((now - cluster.last_seen_at).total_seconds() / 3600)

        if (
            distance_km <= distance_threshold_km
            and time_diff_hours <= time_threshold_hours
        ):
            return cluster

    return None


def create_manual_fire_event(
    session: Session,
    name: str,
    latitude: float,
    longitude: float,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    geometry_wkt: str,
    severity: str = "medium",
    status: str = "active",
    started_at: Optional[datetime] = None,
    source: str = "manual",
    notes: Optional[str] = None,
    reported_by: Optional[str] = None,
    reported_at: Optional[datetime] = None,
    check_duplicates: bool = True,
    duplicate_threshold_km: float = 5.0,
) -> FireEvent:
    """
    Create a manual fire event with optional deduplication against satellite data.

    Args:
        session: Database session
        name: Event name
        latitude: Center latitude
        longitude: Center longitude
        min_lat: Bounding box minimum latitude
        max_lat: Bounding box maximum latitude
        min_lon: Bounding box minimum longitude
        max_lon: Bounding box maximum longitude
        geometry_wkt: Well-known text geometry representation
        severity: Event severity (low, medium, high, critical)
        status: Event status (active, contained, extinguished)
        started_at: Event start time (defaults to now)
        source: Event source (manual, satellite, etc.)
        notes: Operator notes
        reported_by: Person who reported the event
        reported_at: When the event was reported (defaults to now)
        check_duplicates: Whether to check for satellite duplicates
        duplicate_threshold_km: Distance threshold for duplicate detection

    Returns:
        Created FireEvent

    Raises:
        DuplicateFireEventError: If duplicate satellite detection found
        ManualFireEventError: For other creation errors
    """
    if started_at is None:
        started_at = utc_now()

    if reported_at is None:
        reported_at = utc_now()

    # Check for duplicates if requested
    if check_duplicates:
        duplicate = check_for_duplicates(
            session, latitude, longitude, duplicate_threshold_km
        )
        if duplicate:
            raise DuplicateFireEventError(
                f"Manual event at ({latitude}, {longitude}) duplicates satellite "
                f"detection {duplicate.cluster_key} last seen at {duplicate.last_seen_at}"
            )

    # Generate unique event key
    event_key = generate_event_key(latitude, longitude, started_at)

    # Check if event_key already exists (should be very rare)
    existing = session.scalar(select(FireEvent).where(FireEvent.event_key == event_key))
    if existing:
        # Regenerate with microseconds if collision
        event_key = generate_event_key(latitude, longitude, utc_now())

    # Create the event
    event = FireEvent(
        event_key=event_key,
        name=name,
        latitude=latitude,
        longitude=longitude,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        geometry_wkt=geometry_wkt,
        severity=severity,
        status=status,
        started_at=started_at,
        source=source,
        notes=notes,
        reported_by=reported_by,
        reported_at=reported_at,
    )

    session.add(event)
    session.flush()

    return event


def trigger_prediction_for_event(
    session: Session,
    settings: object,
    event: FireEvent,
) -> dict:
    """
    Trigger the spread prediction engine for a fire event (EM-018).

    Runs the Rothermel engine (EM-015) immediately for a freshly created
    event and persists the horizon polygons as FireForecast rows. The
    new-event path bypasses debounce by design: an event with no stored
    forecast always deserves a first run (see spread_trigger.evaluate_trigger
    for the re-trigger rules on condition changes).

    Args:
        session: Database session
        settings: App config (spread engine + trigger settings)
        event: FireEvent to generate prediction for

    Returns:
        Dictionary with prediction status and generated forecast summary
    """
    summary = run_spread_forecast(session, settings, event)
    return {
        "status": "triggered",
        "event_key": event.event_key,
        "model_name": summary["model_name"],
        "message": "Spread forecast generated for all horizons",
        "forecast_count": summary["forecast_count"],
        "horizon_minutes": summary["horizons"],
        "generated_at": summary["generated_at"],
    }
