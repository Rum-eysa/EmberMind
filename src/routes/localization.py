"""Cross-border display standardization endpoints (EM-063, Epic E7).

A stateless presentation helper: localize a UTC instant into the operator's
time zone, format a WGS-84 coordinate in the chosen display format, read a wind
bearing as degrees + compass and describe the fixed metric units. Nothing is
persisted; the ``config`` endpoint tells the UI which preferences are honoured.
"""
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.database import Database
from src.services.localization import (
    COORDINATE_FORMATS,
    DEFAULT_COORDINATE_FORMAT,
    DEFAULT_TIMEZONE,
    LOCALIZATION_ATTRIBUTION,
    LOCALIZATION_PERSISTENCE,
    SUPPORTED_TIMEZONES,
    LocalizationError,
    UNITS,
    standardize,
)


class StandardizeRequest(BaseModel):
    """Optional display inputs; each block is rendered only if its inputs exist."""

    time: str | None = None
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_format: str | None = None
    wind_direction_deg: float | None = None
    distance_km: float | None = None
    area_ha: float | None = None
    speed_kmh: float | None = None


def register_localization_routes(
    api: FastAPI, _database: Database, settings: Any
) -> None:
    """Attach the EM-063 display-standardization endpoints."""

    @api.get("/api/v1/display/config", tags=["display"])
    def display_config() -> dict[str, Any]:
        """Defaults and the knobs the display standardization honours."""
        return {
            "panel": "display_config",
            "defaults": {
                "timezone": getattr(settings, "DISPLAY_TIMEZONE", DEFAULT_TIMEZONE),
                "coordinate_format": getattr(
                    settings, "DISPLAY_COORDINATE_FORMAT", DEFAULT_COORDINATE_FORMAT
                ),
            },
            "supported_timezones": list(SUPPORTED_TIMEZONES),
            "coordinate_formats": list(COORDINATE_FORMATS),
            "units": UNITS,
            "attribution": LOCALIZATION_ATTRIBUTION,
            "persistence": LOCALIZATION_PERSISTENCE,
        }

    @api.post("/api/v1/display/standardize", tags=["display"])
    def display_standardize(req: StandardizeRequest) -> dict[str, Any]:
        """Localize time / format coordinate / read wind / stamp metric units."""
        try:
            return standardize(req.model_dump())
        except LocalizationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "error": str(exc)},
            ) from exc
