"""Proactive resource positioning endpoints (EM-052, Epic E5).

Ranked deployment proposals for a fire event: the nearest available resources,
their closure-aware route to the incident and the estimated arrival time, so the
operator can evaluate a suggestion at a glance on the map.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.road_network import RoadNetworkError
from src.services.positioning import (
    POSITIONING_ATTRIBUTION,
    PositioningError,
    build_proposals,
)


def register_positioning_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the resource-positioning endpoints to the application."""

    @api.get("/api/v1/positioning/proposals", tags=["positioning"])
    def positioning_proposals(
        event_key: str = Query(..., min_length=1),
        limit: int | None = Query(default=None, ge=1, le=50),
    ) -> dict[str, Any]:
        """Rank available resources by route ETA to a fire event's location."""
        try:
            with database.session() as session:
                proposals = build_proposals(session, settings, event_key, limit)
        except PositioningError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "not_found", "error": str(exc)},
            ) from exc
        except RoadNetworkError as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "no_network", "error": str(exc)},
            ) from exc
        return {
            "count": len(proposals),
            "event_key": event_key,
            "attribution": POSITIONING_ATTRIBUTION,
            "proposals": proposals,
        }
