"""Explainable recommendation endpoints (EM-046, Epic E5).

Serves the "why?" panel for a fire event's positioning ranking: the reason each
proposal was recommended, the alternatives that were evaluated but rejected (with
their reasons) and the shared decision context (metric, threshold, closures).
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.positioning import PositioningError
from src.services.recommendation_explain import (
    EXPLAIN_ATTRIBUTION,
    explain_proposals,
)
from src.services.road_network import RoadNetworkError


def register_recommendation_explain_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-046 recommendation-explainability endpoint."""

    @api.get("/api/v1/recommendations/explain", tags=["recommendations"])
    def recommendations_explain(
        event_key: str = Query(..., min_length=1),
        limit: int | None = Query(default=None, ge=1, le=50),
    ) -> dict[str, Any]:
        """Explain the positioning ranking for an event (why + rejected)."""
        try:
            with database.session() as session:
                return explain_proposals(session, settings, event_key, limit)
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

    # Keep the attribution discoverable even when an event has no ranking yet.
    @api.get("/api/v1/recommendations/explain/config", tags=["recommendations"])
    def recommendations_explain_config() -> dict[str, Any]:
        """Descriptor for the explainability panel."""
        return {
            "explain": "positioning",
            "shows_rejected_alternatives": True,
            "ranking_metric": "closure-aware road route ETA",
            "selected_limit_default": int(
                getattr(settings, "POSITIONING_MAX_PROPOSALS", 5)
            ),
            "attribution": EXPLAIN_ATTRIBUTION,
        }
