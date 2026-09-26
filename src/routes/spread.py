"""Rothermel fire spread prediction endpoints (EM-015) and evaluation metrics (EM-017)."""
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.spread import (
    SpreadError,
    fuel_model_catalog,
    list_event_forecasts,
    predict_spread,
)
from src.services.spread_metrics import (
    SpreadMetricsError,
    evaluate_forecast_against_actual,
    list_evaluation_metrics,
    version_summary,
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


class SpreadEvaluateRequest(BaseModel):
    """Request body for evaluating forecasts against actual perimeter (EM-017)."""

    model_config = {"protected_namespaces": ()}

    event_key: str
    actual_perimeter_wkt: str
    actual_area_ha: float
    actual_arrival_time: str | None = None
    model_version: str | None = None


def register_spread_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the fire spread prediction and evaluation endpoints."""

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

    # --- EM-017: Spread evaluation metrics endpoints -----------------------

    @api.post("/api/v1/spread/evaluate", tags=["spread-metrics"])
    def spread_evaluate(req: SpreadEvaluateRequest) -> dict[str, Any]:
        """Evaluate stored forecasts against actual perimeter (IoU, area, time)."""
        try:
            arrival: datetime | None = None
            if req.actual_arrival_time:
                try:
                    arrival = datetime.fromisoformat(req.actual_arrival_time)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "status": "error",
                            "error": "actual_arrival_time must be ISO-8601",
                        },
                    ) from exc
            with database.session() as session:
                metrics = evaluate_forecast_against_actual(
                    session,
                    event_key=req.event_key,
                    actual_perimeter_wkt=req.actual_perimeter_wkt,
                    actual_area_ha=req.actual_area_ha,
                    actual_arrival_time=arrival,
                    model_version=req.model_version,
                )
                return {
                    "status": "ok",
                    "event_key": req.event_key,
                    "count": len(metrics),
                    "metrics": metrics,
                }
        except SpreadMetricsError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/spread/metrics", tags=["spread-metrics"])
    def spread_metrics(
        event_key: str | None = Query(default=None),
        model_version: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        """List stored evaluation metrics, optionally filtered."""
        with database.session() as session:
            rows = list_evaluation_metrics(session, event_key, model_version, limit)
            return {
                "count": len(rows),
                "metrics": rows,
            }

    @api.get("/api/v1/spread/metrics/summary", tags=["spread-metrics"])
    def spread_metrics_summary(
        model_version: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Aggregated metrics per model version (mean IoU, area error, etc.)."""
        with database.session() as session:
            summaries = version_summary(session, model_version)
            return {
                "count": len(summaries),
                "versions": summaries,
            }
