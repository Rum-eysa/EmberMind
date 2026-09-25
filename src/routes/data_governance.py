"""Data source license, attribution and quota governance endpoints."""
from typing import Any

from fastapi import FastAPI

from src.database import Database
from src.services.data_governance import (
    attribution_block,
    cache_plan_report,
    license_table,
)


def register_data_governance_routes(
    api: FastAPI, _database: Database, settings: Any
) -> None:
    """Attach the data-source governance endpoints to the application.

    These endpoints are served entirely from the static governance registry,
    so no database session is required.
    """

    @api.get("/api/v1/data-sources", tags=["data-governance"])
    def data_sources() -> dict[str, Any]:
        """License, attribution and quota table for every external source."""
        return license_table(settings)

    @api.get("/api/v1/data-sources/attribution", tags=["data-governance"])
    def data_sources_attribution() -> dict[str, Any]:
        """Attribution texts to render in the UI and in exported products."""
        return attribution_block(settings)

    @api.get("/api/v1/data-sources/cache-plan", tags=["data-governance"])
    def data_sources_cache_plan() -> dict[str, Any]:
        """Cache plans for sources carrying quota-overrun risk."""
        return cache_plan_report(settings)
