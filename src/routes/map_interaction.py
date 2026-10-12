"""Map interaction endpoints (EM-080, Epic E8).

The operator map's basemap switcher, place/coordinate search and distance/area
ruler. Every endpoint is read-only: the basemap catalogue and gazetteer ship
with the code, and a measurement is a stateless calculation over the points the
client already clicked. ``config`` tells the UI the knobs it must honour.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.map_interaction import (
    MapInteractionError,
    map_interaction_config,
    measure_area,
    measure_distance,
    search_places,
)


class MeasureRequest(BaseModel):
    """An ordered list of ``[latitude, longitude]`` pairs for a measurement."""

    points: list[list[float]]


def register_map_interaction_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-080 basemap / search / measurement endpoints."""
    del database  # read-only over shipped catalogue; no persistence

    @api.get("/api/v1/map/config", tags=["map-interaction"])
    def config() -> dict[str, Any]:
        """Basemaps, search limit and measurement caps for the operator map."""
        return map_interaction_config(settings)

    @api.get("/api/v1/map/search", tags=["map-interaction"])
    def search(
        query: str = Query(default="", alias="q", max_length=120),
    ) -> dict[str, Any]:
        """Resolve a place name or a raw ``"lat, lon"`` coordinate."""
        return search_places(query, settings)

    @api.post("/api/v1/map/measure/distance", tags=["map-interaction"])
    def distance(req: MeasureRequest) -> dict[str, Any]:
        """Great-circle distance along the clicked polyline."""
        try:
            return measure_distance(req.points, settings)
        except MapInteractionError as exc:
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.post("/api/v1/map/measure/area", tags=["map-interaction"])
    def area(req: MeasureRequest) -> dict[str, Any]:
        """Geodesic area (ha / km^2) of the clicked polygon."""
        try:
            return measure_area(req.points, settings)
        except MapInteractionError as exc:
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "error": str(exc)},
            ) from exc
