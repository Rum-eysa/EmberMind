"""Recommendation impact-comparison endpoints (EM-048, Epic E5).

Serves the side-by-side risk profile for a fire event: how the risk levels move
**if the positioning recommendation is applied** versus **if it is not**, so the
commander can see the value of the decision before acting on it. Ephemeral and
advisory only - no resources are booked or mutated.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.positioning import PositioningError
from src.services.recommendation_impact import (
    IMPACT_ATTRIBUTION,
    ImpactError,
    compare_impact,
)
from src.services.risk_index import RiskIndexError
from src.services.road_network import RoadNetworkError


def register_recommendation_impact_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-048 recommendation-impact comparison endpoint."""

    @api.get("/api/v1/recommendations/impact", tags=["recommendations"])
    def recommendations_impact(
        event_key: str = Query(..., min_length=1)
    ) -> dict[str, Any]:
        """Side-by-side applied-vs-not-applied risk profile for one event."""
        try:
            with database.session() as session:
                return compare_impact(session, settings, event_key)
        except (PositioningError, RiskIndexError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "not_found", "error": str(exc)},
            ) from exc
        except (RoadNetworkError, ImpactError) as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "not_comparable", "error": str(exc)},
            ) from exc

    # Keep the attribution discoverable even before an event is chosen.
    @api.get("/api/v1/recommendations/impact/config", tags=["recommendations"])
    def recommendations_impact_config() -> dict[str, Any]:
        """Descriptor for the impact-comparison panel."""
        return {
            "impact": "recommendation",
            "compares": ["if_applied", "if_not_applied"],
            "risk_metric": "EM-029 demand/adequate-capacity ratio per horizon",
            "persistence": "none",
            "attribution": IMPACT_ATTRIBUTION,
        }
