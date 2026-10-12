"""Read-only municipality monitoring view endpoints (EM-083, Epic E8).

A simplified, monitoring-only projection of the region's active fires and local
resource status for a municipal manager. The operator console's decision controls
are intentionally absent. Nothing is persisted.
"""
from typing import Any

from fastapi import FastAPI, Query

from src.database import Database
from src.services.municipality_view import (
    municipality_view,
    municipality_view_config,
)


def register_municipality_view_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-083 read-only municipality view."""

    @api.get("/api/v1/municipality-view/config", tags=["panel"])
    def municipality_view_config_endpoint() -> dict[str, Any]:
        """Region box, vocabularies and the operator controls hidden here."""
        return municipality_view_config(settings)

    @api.get("/api/v1/municipality-view", tags=["panel"])
    def municipality_view_endpoint(
        severity: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Simplified region status: active fires, headline and local capacity."""
        with database.session() as session:
            return municipality_view(session, settings, severity=severity)
