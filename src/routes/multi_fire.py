"""Multi-fire management survey endpoints (EM-082, Epic E8).

Read-only projection over the active fires, their committed suppression units
and the cross-fire resource-sharing conflicts a coordinator must act on. Nothing
new is persisted.
"""
from typing import Any

from fastapi import FastAPI, Query

from src.database import Database
from src.services.multi_fire import multi_fire_config, multi_fire_overview


def register_multi_fire_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the EM-082 multi-fire management survey."""

    @api.get("/api/v1/multi-fire/config", tags=["panel"])
    def multi_fire_config_endpoint() -> dict[str, Any]:
        """Severities, busy statuses, conflict taxonomy and survey bounds."""
        return multi_fire_config(settings)

    @api.get("/api/v1/multi-fire", tags=["panel"])
    def multi_fire_feed(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Active-fire survey with committed rosters and conflict warnings."""
        with database.session() as session:
            return multi_fire_overview(session, settings, event_key=event_key)
