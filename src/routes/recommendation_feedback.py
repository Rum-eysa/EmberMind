"""Recommendation accept/reject feedback analytics endpoints (EM-054, Epic E5).

A read-only report over the EM-047 decision audit: accept/reject rates, the most
-rejected resource types, the recorded reasons and distilled improvement ideas -
the signal a data scientist needs to tune the recommendation engine.
"""
from typing import Any

from fastapi import FastAPI, Query

from src.database import Database
from src.models.recommendation import DECISION_ACTIONS
from src.services.recommendation_feedback import (
    FEEDBACK_ATTRIBUTION,
    FEEDBACK_PERSISTENCE,
    FEEDBACK_SOURCE,
    feedback_summary,
)


def register_recommendation_feedback_routes(
    api: FastAPI, database: Database, _settings: Any
) -> None:
    """Attach the EM-054 recommendation-feedback endpoints."""

    @api.get("/api/v1/recommendations/feedback", tags=["recommendations"])
    def recommendations_feedback(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Accept/reject analysis over the operator decision audit."""
        with database.session() as session:
            return feedback_summary(session, event_key)

    @api.get("/api/v1/recommendations/feedback/config", tags=["recommendations"])
    def recommendations_feedback_config() -> dict[str, Any]:
        """Descriptor: what the feedback loop measures and how."""
        return {
            "panel": "recommendation_feedback",
            "actions": list(DECISION_ACTIONS),
            "excludes": ["release"],
            "measures": [
                "accept_rate",
                "reject_rate",
                "edit_rate",
                "by_resource_type",
                "most_rejected_types",
                "rejection_reasons",
                "improvement_ideas",
            ],
            "source": FEEDBACK_SOURCE,
            "persistence": FEEDBACK_PERSISTENCE,
            "attribution": FEEDBACK_ATTRIBUTION,
        }
