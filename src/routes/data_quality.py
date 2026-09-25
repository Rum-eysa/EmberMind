"""Data quality and freshness monitoring endpoints."""
from typing import Any

from fastapi import FastAPI

from src.database import Database
from src.services.data_quality import (
    evaluate_data_quality,
    get_data_quality_warnings,
)


def register_data_quality_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the data-quality monitoring endpoints to the application."""

    @api.get("/api/v1/data-quality", tags=["data-quality"])
    def data_quality() -> dict[str, Any]:
        """Report last successful pull time and freshness status per source."""
        with database.session() as session:
            return evaluate_data_quality(session, settings)

    @api.get("/api/v1/data-quality/warnings", tags=["data-quality"])
    def data_quality_warnings() -> dict[str, Any]:
        """Return operator-visible warnings for sources broken beyond threshold."""
        with database.session() as session:
            return get_data_quality_warnings(session, settings)
