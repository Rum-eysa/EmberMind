"""Mobile/tablet field view endpoints (EM-084, Epic E8).

A single phone-legible projection that composes the EM-051 task card and the
EM-029 nearby risk zone for a field team. Read-only and computed live; the
``config`` endpoint tells the mobile client the proximity radius and item caps it
must honour.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.field_view import FieldViewError, field_view, field_view_config


def register_field_view_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the EM-084 field-view endpoints."""

    @api.get("/api/v1/field-view", tags=["field-view"])
    def view(
        resource_key: str | None = Query(default=None, min_length=1, max_length=120),
        event_key: str | None = Query(default=None, min_length=1, max_length=120),
        latitude: float | None = Query(default=None, ge=-90.0, le=90.0),
        longitude: float | None = Query(default=None, ge=-180.0, le=180.0),
    ) -> dict[str, Any]:
        """This team's task card(s) plus the nearest active risk zones.

        An unknown ``event_key`` yields **404**; otherwise the view is returned
        even when empty, so the phone can render its empty state.
        """
        try:
            with database.session() as session:
                return field_view(
                    session,
                    settings,
                    resource_key=resource_key,
                    event_key=event_key,
                    latitude=latitude,
                    longitude=longitude,
                )
        except FieldViewError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "not_found", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/field-view/config", tags=["field-view"])
    def config() -> dict[str, Any]:
        """Proximity radius, item cap and data sources for the mobile view."""
        return field_view_config(settings)
