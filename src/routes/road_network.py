"""OpenStreetMap road-network accessibility routes (import, closures, crew ETA)."""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.database import Database
from src.models.road_network import CrewBase, RoadClosure, RoadSegment
from src.services.grid_standard import PilotRegionGridService
from src.services.road_network import (
    RoadNetworkError,
    RoadSegmentNotFoundError,
    compute_arrival_for_event,
    compute_crew_arrival,
    mark_road_closure,
    resolve_road_closure,
    sync_road_network,
)


class RoadSyncRequest(BaseModel):
    """Optional bbox override for an OpenStreetMap road network import."""

    min_lat: float | None = None
    max_lat: float | None = None
    min_lon: float | None = None
    max_lon: float | None = None


class RoadClosureRequest(BaseModel):
    """Request payload to mark a road segment as closed."""

    segment_key: str
    reason: str = "unspecified"
    reported_by: str | None = None


class CrewEtaRequest(BaseModel):
    """Request payload for a direct crew arrival ETA query."""

    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float


class CrewArrivalRequest(BaseModel):
    """Request payload for ranking crew bases against a fire location."""

    fire_lat: float
    fire_lon: float


class CrewBaseRequest(BaseModel):
    """Request payload to register a crew base."""

    base_key: str
    name: str
    latitude: float
    longitude: float
    crew_type: str = "first_response"
    available: bool = True


def _resolve_bbox(req: RoadSyncRequest) -> tuple[float, float, float, float]:
    grid_service = PilotRegionGridService()
    return (
        req.min_lat if req.min_lat is not None else grid_service.min_lat,
        req.min_lon if req.min_lon is not None else grid_service.min_lon,
        req.max_lat if req.max_lat is not None else grid_service.max_lat,
        req.max_lon if req.max_lon is not None else grid_service.max_lon,
    )


def register_road_network_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the road-network and routing endpoints to the application."""

    @api.get("/api/v1/roads", tags=["roads"])
    def list_roads(
        limit: int = Query(default=200, ge=1, le=2000),
        highway: str | None = None,
    ) -> dict[str, Any]:
        """List imported OpenStreetMap road segments."""
        with database.session() as session:
            query = select(RoadSegment)
            if highway:
                query = query.where(RoadSegment.highway == highway)
            rows = session.scalars(
                query.order_by(RoadSegment.id.asc()).limit(limit)
            ).all()
            segments = [row.as_dict for row in rows]
        return {
            "source": "OpenStreetMap",
            "count": len(segments),
            "segments": segments,
        }

    @api.post("/api/v1/roads/sync", tags=["roads"])
    def roads_sync(req: RoadSyncRequest) -> dict[str, Any]:
        """Import the OpenStreetMap road network for the pilot region (or a bbox override)."""
        bbox = _resolve_bbox(req)
        try:
            with database.session() as session:
                result = sync_road_network(session, settings, bbox)
                return {"status": "ok", "bbox": bbox, **result}
        except RoadNetworkError as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/roads/closures", tags=["roads"])
    def list_closures(
        status: str = "active",
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        """List road closures filtered by status."""
        with database.session() as session:
            rows = session.scalars(
                select(RoadClosure)
                .where(RoadClosure.status == status)
                .order_by(RoadClosure.reported_at.desc())
                .limit(limit)
            ).all()
            closures = [row.as_dict for row in rows]
        return {"count": len(closures), "closures": closures}

    @api.post("/api/v1/roads/closures", tags=["roads"])
    def create_closure(req: RoadClosureRequest) -> dict[str, Any]:
        """Mark a road segment closed; subsequent ETA queries re-route around it."""
        try:
            with database.session() as session:
                closure = mark_road_closure(
                    session, req.segment_key, req.reason, req.reported_by
                )
                return {"status": "closed", "closure": closure.as_dict}
        except RoadSegmentNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "not_found", "error": str(exc)},
            ) from exc
        except RoadNetworkError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.delete("/api/v1/roads/closures/{segment_key}", tags=["roads"])
    def delete_closure(segment_key: str) -> dict[str, Any]:
        """Resolve active closures on a road segment."""
        with database.session() as session:
            resolved = resolve_road_closure(session, segment_key)
        if resolved == 0:
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "not_found",
                    "error": f"No active closure on segment {segment_key}",
                },
            )
        return {"status": "resolved", "segment_key": segment_key, "resolved": resolved}

    @api.get("/api/v1/crew-bases", tags=["roads"])
    def list_crew_bases(
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        """List registered firefighting crew bases."""
        with database.session() as session:
            rows = session.scalars(
                select(CrewBase).order_by(CrewBase.id.asc()).limit(limit)
            ).all()
            bases = [row.as_dict for row in rows]
        return {"count": len(bases), "crew_bases": bases}

    @api.post("/api/v1/crew-bases", tags=["roads"])
    def create_crew_base(req: CrewBaseRequest) -> dict[str, Any]:
        """Register a firefighting crew base used as a routing origin."""
        with database.session() as session:
            existing = session.scalar(
                select(CrewBase).where(CrewBase.base_key == req.base_key)
            )
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "status": "duplicate",
                        "error": f"Crew base {req.base_key} already exists",
                    },
                )
            base = CrewBase(
                base_key=req.base_key,
                name=req.name,
                latitude=req.latitude,
                longitude=req.longitude,
                crew_type=req.crew_type,
                available=req.available,
            )
            session.add(base)
            session.flush()
            return {"status": "created", "crew_base": base.as_dict}

    @api.post("/api/v1/routing/eta", tags=["routing"])
    def routing_eta(req: CrewEtaRequest) -> dict[str, Any]:
        """Compute a crew's estimated arrival time between two points (closure-aware)."""
        access_speed = float(getattr(settings, "ROAD_ACCESS_SPEED_KMH", 40.0))
        try:
            with database.session() as session:
                route = compute_crew_arrival(
                    session,
                    (req.origin_lat, req.origin_lon),
                    (req.dest_lat, req.dest_lon),
                    access_speed_kmh=access_speed,
                )
                return {"status": "ok", "route": route.as_dict()}
        except RoadSegmentNotFoundError as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "no_network", "error": str(exc)},
            ) from exc

    @api.post("/api/v1/routing/crew-arrival", tags=["routing"])
    def routing_crew_arrival(req: CrewArrivalRequest) -> dict[str, Any]:
        """Rank available crew bases by realistic arrival time at a fire location."""
        access_speed = float(getattr(settings, "ROAD_ACCESS_SPEED_KMH", 40.0))
        with database.session() as session:
            arrivals = compute_arrival_for_event(
                session, (req.fire_lat, req.fire_lon), access_speed_kmh=access_speed
            )
        return {"count": len(arrivals), "crews": arrivals}
