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
    CONSTRAINT_ATTRIBUTION,
    CONSTRAINT_NAMES,
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
        rejected: list[dict[str, Any]] = []
        try:
            with database.session() as session:
                proposals = build_proposals(
                    session, settings, event_key, limit, rejected_out=rejected
                )
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
            # EM-050: constraint-violating origins never reach the list;
            # they surface here with the violated constraints and a reason.
            "rejected": rejected,
            "rejected_count": len(rejected),
        }

    @api.get("/api/v1/positioning/constraints", tags=["positioning"])
    def positioning_constraints() -> dict[str, Any]:
        """EM-050 descriptor: which constraints are enforced and how."""
        return {
            "constraints": list(CONSTRAINT_NAMES),
            "fields": {
                "range_km": "menzil (tek yön km) — rot mesafesi aşarsa elenir",
                "shift_minutes": "mesai/yakıt — ETA aşarsa elenir",
                "night_capable": "gece yetkisi — varış gece penceresine denk "
                "gelirse ve yetki yoksa elenir",
                "road_closure": "kapalı yollar nedeniyle ulaşılamayan elenir",
            },
            "resource_count_limit": int(
                getattr(settings, "POSITIONING_MAX_PROPOSALS", 5)
            ),
            "night_ban_enabled": bool(
                getattr(settings, "POSITIONING_NIGHT_BAN_ENABLED", True)
            ),
            "unbounded_means_unknown": True,
            "persistence": "none",
            "attribution": CONSTRAINT_ATTRIBUTION,
        }
