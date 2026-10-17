"""Spatial query and manual fire-event endpoints (fire events, silent regions).

Extracted from the create_fastapi_app monolith (code-quality audit A-6, step 2)
into the project's standard ``register_*_routes`` module. Behaviour-preserving:
the model declarations, the ``parse_datetime`` helper and the route bodies are
moved verbatim; the same routes are registered in the same order via the single
``register_spatial_event_routes`` call placed exactly where the inline block
used to sit, so route registration order (and thus the OpenAPI surface) is
unchanged. The manual-fire-event PUT/DELETE handlers stay inline for now
because they are interleaved with the grid and pipeline route blocks.
"""
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.database import Database
from src.models.spatial import FireEvent, SilentRegion
from src.services.live import safe_record_update
from src.services.manual_fire_event import (
    DuplicateFireEventError,
    ManualFireEventError,
    create_manual_fire_event,
    trigger_prediction_for_event,
)
from src.services.spread import SpreadError
from src.services.spatial_db import (
    SpatialQueryError,
    execute_polygon_intersection_query,
)


class ManualFireEventRequest(BaseModel):
    """Request payload for manual fire event creation."""

    name: str
    latitude: float
    longitude: float
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    geometry_wkt: str
    severity: str = "medium"
    status: str = "active"
    started_at: str | None = None
    source: str = "manual"
    notes: str | None = None
    reported_by: str | None = None
    reported_at: str | None = None
    check_duplicates: bool = True
    duplicate_threshold_km: float = 5.0
    trigger_prediction: bool = True


class ManualFireEventResponse(BaseModel):
    """Response for manual fire event creation."""

    status: str
    event: dict[str, Any]
    duplicate_warning: str | None = None
    prediction_triggered: dict[str, Any] | None = None


class PolygonIntersectionRequest(BaseModel):
    """Request payload for spatial polygon intersection queries."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse an ISO datetime string (optional Z suffix) into a naive UTC datetime.

    Returns ``None`` only for an absent value; a malformed string is rejected
    with 422 instead of silently falling back to "now".
    """
    if not dt_str:
        return None
    try:
        # Handle Z suffix (UTC)
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        parsed = datetime.fromisoformat(dt_str)
        # Remove timezone info for compatibility with database
        return parsed.replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "error",
                "error": f"invalid ISO-8601 datetime: {dt_str!r}",
            },
        ) from exc


def register_spatial_event_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the spatial query and manual fire-event read/create endpoints."""

    @api.get("/api/v1/spatial/events", tags=["spatial"])
    def spatial_events(
        limit: int = Query(default=100, ge=1, le=1000),
        source: str | None = None,
    ) -> dict[str, Any]:
        with database.session() as session:
            query = select(FireEvent)
            if source:
                query = query.where(FireEvent.source == source)
            rows = session.scalars(
                query.order_by(FireEvent.started_at.desc()).limit(limit)
            ).all()
            return {
                "source": "PostGIS/Spatial",
                "count": len(rows),
                "events": [r.as_dict for r in rows],
            }

    @api.get("/api/v1/events/{event_key}", tags=["events"])
    def get_event(event_key: str) -> dict[str, Any]:
        """Get a single fire event by event_key."""
        with database.session() as session:
            event = session.scalar(
                select(FireEvent).where(FireEvent.event_key == event_key)
            )

            if not event:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "status": "not_found",
                        "error": f"Event {event_key} not found",
                    },
                )

            return {
                "status": "ok",
                "event": event.as_dict,
            }

    @api.get("/api/v1/spatial/silent-regions", tags=["spatial"])
    def spatial_silent_regions() -> dict[str, Any]:
        with database.session() as session:
            rows = session.scalars(
                select(SilentRegion).where(SilentRegion.is_active.is_(True))
            ).all()
            return {
                "source": "PostGIS/Spatial",
                "count": len(rows),
                "silent_regions": [r.as_dict for r in rows],
            }

    @api.post("/api/v1/spatial/polygon-intersection", tags=["spatial"])
    def spatial_polygon_intersection(
        req: PolygonIntersectionRequest,
    ) -> dict[str, Any]:
        try:
            with database.session() as session:
                return execute_polygon_intersection_query(
                    session, req.min_lat, req.max_lat, req.min_lon, req.max_lon
                )
        except SpatialQueryError as exc:
            raise HTTPException(
                status_code=500,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.post(
        "/api/v1/events/manual",
        response_model=ManualFireEventResponse,
        tags=["events"],
    )
    def create_manual_event(req: ManualFireEventRequest) -> dict[str, Any]:
        """Create a manual fire event with optional deduplication and prediction triggering."""
        try:
            with database.session() as session:
                started_at = parse_datetime(req.started_at)
                reported_at = parse_datetime(req.reported_at)

                # Create the manual event
                event = create_manual_fire_event(
                    session,
                    name=req.name,
                    latitude=req.latitude,
                    longitude=req.longitude,
                    min_lat=req.min_lat,
                    max_lat=req.max_lat,
                    min_lon=req.min_lon,
                    max_lon=req.max_lon,
                    geometry_wkt=req.geometry_wkt,
                    severity=req.severity,
                    status=req.status,
                    started_at=started_at,
                    source=req.source,
                    notes=req.notes,
                    reported_by=req.reported_by,
                    reported_at=reported_at,
                    check_duplicates=req.check_duplicates,
                    duplicate_threshold_km=req.duplicate_threshold_km,
                )

                # Trigger prediction if requested (EM-018: on by default,
                # a failed forecast run must not roll back event creation)
                prediction_result = None
                if req.trigger_prediction:
                    try:
                        prediction_result = trigger_prediction_for_event(
                            session, settings, event
                        )
                    except SpreadError as exc:
                        prediction_result = {
                            "status": "error",
                            "event_key": event.event_key,
                            "error": str(exc),
                        }

                safe_record_update(
                    database,
                    settings,
                    "fire_event",
                    event_key=str(event.event_key),
                    title="Yeni manuel yangın olayı",
                    message=str(event.name),
                    payload={
                        "status": event.status,
                        "severity": event.severity,
                        "prediction_triggered": prediction_result is not None,
                    },
                    source="manual",
                )

                return {
                    "status": "created",
                    "event": event.as_dict,
                    "prediction_triggered": prediction_result,
                }
        except DuplicateFireEventError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "duplicate",
                    "error": str(exc),
                    "message": "Manual event location duplicates existing satellite detection",
                },
            ) from exc
        except ManualFireEventError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
