"""Fire Weather Index (FWI) and drought indicator endpoints."""
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.data_governance import attribution_for
from src.services.fwi import (
    compute_region_fwi,
    daily_summary,
    fwi_map_layer,
    list_fwi_rows,
)


def _parse_day(day: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD query parameter."""
    if not day:
        return None
    try:
        return date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error": f"Invalid day '{day}'; use YYYY-MM-DD"},
        ) from exc


def register_fwi_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the Fire Weather Index / drought indicator endpoints."""

    @api.get("/api/v1/fwi", tags=["fwi"])
    def fwi_zones(day: str | None = None) -> dict[str, Any]:
        """Zone FWI profiles stored for a day (latest day by default)."""
        with database.session() as session:
            target_day, rows = list_fwi_rows(session, settings, _parse_day(day))
            return {
                "layer": "fire_weather_index",
                "day": target_day.isoformat() if target_day else None,
                "count": len(rows),
                "zones": [row.as_dict for row in rows],
                "attribution": attribution_for(settings, "weather"),
            }

    @api.get("/api/v1/fwi/map", tags=["fwi"])
    def fwi_map(day: str | None = None) -> dict[str, Any]:
        """GeoJSON polygon layer of zone FWI risk for UI map rendering."""
        with database.session() as session:
            return fwi_map_layer(session, settings, _parse_day(day))

    @api.get("/api/v1/fwi/daily-summary", tags=["fwi"])
    def fwi_daily_summary(day: str | None = None) -> dict[str, Any]:
        """Daily digest of high-FWI zones and drought watch areas."""
        with database.session() as session:
            summary = daily_summary(session, settings, _parse_day(day))
            return {**summary, "attribution": attribution_for(settings, "weather")}

    @api.post("/api/v1/fwi/compute", tags=["fwi"])
    def fwi_compute(day: str | None = Query(default=None)) -> dict[str, Any]:
        """Compute (or recompute) the FWI layer for one day from stored weather."""
        with database.session() as session:
            result = compute_region_fwi(session, settings, _parse_day(day))
            return {"status": "ok", **result}
