"""Rothermel fire spread prediction endpoints (EM-015)."""
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.database import Database
from src.services.spread import (
    SpreadError,
    fuel_model_catalog,
    list_event_forecasts,
    predict_spread,
)


class SpreadPredictRequest(BaseModel):
    """Spread prediction inputs; omit fields to resolve them from stored data."""

    latitude: float
    longitude: float
    event_key: str | None = None
    wind_speed_kmh: float | None = None
    wind_from_deg: float | None = None
    air_temp_c: float | None = None
    relative_humidity_pct: float | None = None
    fuel_moisture_pct: float | None = None
    slope_deg: float | None = None
    aspect_deg: float | None = None
    fuel_model: str | None = None
    horizon_minutes: list[int] | None = None


def register_spread_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the fire spread prediction endpoints."""

    @api.post("/api/v1/spread/predict", tags=["spread"])
    def spread_predict(req: SpreadPredictRequest) -> dict[str, Any]:
        """Run the Rothermel engine for 30/60/120-minute risk-zone polygons."""
        try:
            with database.session() as session:
                return predict_spread(session, settings, req.model_dump())
        except SpreadError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/spread/fuel-models", tags=["spread"])
    def spread_fuel_models() -> dict[str, Any]:
        """List the standard fuel models and their computed bed intermediates."""
        return {
            "model": str(getattr(settings, "SPREAD_MODEL_NAME", "rothermel_v1")),
            "count": len(fuel_model_catalog()),
            "fuel_models": fuel_model_catalog(),
        }

    @api.get("/api/v1/spread/forecasts", tags=["spread"])
    def spread_forecasts(event_key: str | None = None) -> dict[str, Any]:
        """Stored spread forecasts, newest first (optionally per event)."""
        with database.session() as session:
            rows = list_event_forecasts(session, event_key)
            return {
                "layer": "fire_spread_forecast",
                "count": len(rows),
                "forecasts": rows,
            }
