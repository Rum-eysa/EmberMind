"""Manual fire event creation service with deduplication and prediction triggering."""
from datetime import datetime, timezone
from math import cos
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster
from src.models.spatial import FireEvent


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

    now = datetime.now(timezone.utc).replace(tzinfo=None)

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
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if reported_at is None:
        reported_at = datetime.now(timezone.utc).replace(tzinfo=None)

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
        event_key = generate_event_key(
            latitude, longitude, datetime.now(timezone.utc).replace(tzinfo=None)
        )

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
    event: FireEvent,
    model_name: str = "default",
) -> dict:
    """
    Trigger automatic prediction for a fire event.

    This is a placeholder for the actual prediction service integration.
    In a full implementation, this would:
    1. Call the ML prediction service
    2. Store the forecast in fire_forecasts table
    3. Return prediction results

    Args:
        session: Database session
        event: FireEvent to generate prediction for
        model_name: Name of the prediction model to use

    Returns:
        Dictionary with prediction status and results
    """
    # Placeholder: In a real implementation, this would call the prediction service
    # For now, we'll simulate a successful trigger

    return {
        "status": "triggered",
        "event_key": event.event_key,
        "model_name": model_name,
        "message": "Prediction job queued for processing",
        "forecast_id": None,  # Would be populated when forecast is created
    }
