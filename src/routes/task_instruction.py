"""Field task-instruction card endpoints (EM-051, Epic E5).

Turns an accepted positioning proposal into a short field task card - target,
ETA and a risk note - reconstructed from the EM-047 decision audit and the
EM-029 risk engine. Read-only and computed live.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.task_instruction import (
    TASK_CARD_ATTRIBUTION,
    TaskInstructionError,
    generate_task_cards,
)


def register_task_instruction_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-051 task-instruction endpoints."""

    @api.get("/api/v1/recommendations/task-cards", tags=["recommendations"])
    def task_cards(
        event_key: str | None = Query(default=None, min_length=1)
    ) -> dict[str, Any]:
        """Short field task cards for every committed proposal.

        ``event_key`` is optional; when supplied, only that incident's cards are
        returned and an unknown event yields **404**.
        """
        try:
            with database.session() as session:
                cards = generate_task_cards(session, settings, event_key)
        except TaskInstructionError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "not_found", "error": str(exc)},
            ) from exc
        return {
            "count": len(cards),
            "event_key": event_key,
            "cards": cards,
            "attribution": TASK_CARD_ATTRIBUTION,
        }

    @api.get("/api/v1/recommendations/task-cards/config", tags=["recommendations"])
    def task_cards_config() -> dict[str, Any]:
        """Descriptor for the field task-card workflow."""
        return {
            "source": "accepted positioning proposals (EM-047 audit)",
            "fields": ["target", "eta_minutes", "risk_note"],
            "persistence": "none",
            "attribution": TASK_CARD_ATTRIBUTION,
        }
