"""Exposure/threat-analysis endpoints (EM-023, Epic E2).

Which village, road and energy line lies in the fire's path and when it will
first be affected — for protection and evacuation prioritisation.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.exposure import (
    ExposureError,
    exposure_summary,
    sync_exposed_assets,
)
from src.services.grid_standard import PilotRegionGridService


class ExposureImportRequest(BaseModel):
    """Optional bbox override for an OpenStreetMap exposure-asset import."""

    min_lat: float | None = None
    max_lat: float | None = None
    min_lon: float | None = None
    max_lon: float | None = None


def _resolve_bbox(req: ExposureImportRequest) -> tuple[float, float, float, float]:
    grid = PilotRegionGridService()
    return (
        req.min_lat if req.min_lat is not None else grid.min_lat,
        req.min_lon if req.min_lon is not None else grid.min_lon,
        req.max_lat if req.max_lat is not None else grid.max_lat,
        req.max_lon if req.max_lon is not None else grid.max_lon,
    )


def register_exposure_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the exposure/threat-analysis endpoints to the application."""

    @api.post("/api/v1/exposure/import", tags=["exposure"])
    def exposure_import(req: ExposureImportRequest) -> dict[str, Any]:
        """Import settlements and energy lines for a bbox from OpenStreetMap."""
        bbox = _resolve_bbox(req)
        try:
            with database.session() as session:
                return sync_exposed_assets(session, settings, bbox)
        except ExposureError as exc:
            raise HTTPException(
                status_code=502,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/exposure", tags=["exposure"])
    def exposure_list(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Sorted list of threatened settlements/roads/lines with T+impact time."""
        with database.session() as session:
            return exposure_summary(session, settings, event_key)
