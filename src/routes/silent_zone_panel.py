"""Silent-zone confidence panel endpoints (EM-078, Epic E8).

Read-only projection over the existing ``silent_regions`` data: grade each active
silent zone by confidence (fire contradiction + proximity), sort, and optionally
filter by band. The operator map uses the returned bounding boxes for map-synced
selection. Nothing new is persisted.
"""
from typing import Any

from fastapi import FastAPI, Query

from src.database import Database
from src.services.silent_zone_panel import silent_zone_report, zone_config


def register_silent_zone_panel_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-078 silent-zone confidence feed."""

    @api.get("/api/v1/silent-zones/config", tags=["panel"])
    def silent_zones_config() -> dict[str, Any]:
        """Bands, cut-offs and the confidence derivation the panel uses."""
        return zone_config(settings)

    @api.get("/api/v1/silent-zones", tags=["panel"])
    def silent_zones(
        confidence: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Confidence-graded, sorted silent-zone list (optional band filter)."""
        with database.session() as session:
            return silent_zone_report(session, settings, confidence)
