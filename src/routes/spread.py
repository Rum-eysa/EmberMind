"""Rothermel fire spread prediction endpoints (EM-015), evaluation metrics
(EM-017), dead fuel moisture model endpoints (EM-019), uncertainty envelope
endpoints (EM-020) and natural barrier management (EM-021)."""
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.database import Database
from src.models.spatial import FireEvent
from src.services.barriers import (
    BarrierError,
    delete_barrier,
    list_barriers,
    register_barrier,
)
from src.services.fuel_moisture import FuelMoistureError, dead_fuel_moisture
from src.services.spread import (
    SpreadError,
    effective_dead_fuel_moisture,
    fuel_model_catalog,
    list_event_forecasts,
    predict_spread,
    resolve_fuel_model_number,
)
from src.services.spread_metrics import (
    SpreadMetricsError,
    evaluate_forecast_against_actual,
    list_evaluation_metrics,
    version_summary,
)
from src.services.spread_trigger import (
    auto_trigger_forecasts,
    evaluate_trigger,
)
from src.services.spread_uncertainty import uncertainty_envelope


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


class BarrierRequest(BaseModel):
    """Request body for registering an EM-021 natural barrier."""

    name: str
    barrier_type: str
    geometry_wkt: str
    barrier_key: str | None = None
    slowdown_factor: float | None = None
    is_active: bool = True
    source: str = "operator"
    notes: str | None = None


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

    # --- EM-019: dead fuel moisture model endpoints -------------------------

    @api.get("/api/v1/spread/fuel-moisture", tags=["spread-moisture"])
    def spread_fuel_moisture(
        air_temp_c: float = Query(..., ge=-60, le=60, description="Air temp [degC]"),
        relative_humidity_pct: float = Query(
            ..., ge=0, le=100, description="Relative humidity [%]"
        ),
        fuel_model: str
        | None = Query(
            default=None, description="Fuel model label/id for effective moisture"
        ),
    ) -> dict[str, Any]:
        """1h/10h/100h dead fuel moisture classes from temperature and humidity."""
        try:
            classes = dead_fuel_moisture(
                air_temp_c,
                relative_humidity_pct,
                temp_amplitude_c=float(
                    getattr(settings, "FUEL_MOISTURE_DIURNAL_TEMP_AMPLITUDE_C", 8.0)
                ),
                rh_amplitude_pct=float(
                    getattr(settings, "FUEL_MOISTURE_DIURNAL_RH_AMPLITUDE_PCT", 25.0)
                ),
                conditioning_hours=int(
                    getattr(settings, "FUEL_MOISTURE_CONDITIONING_HOURS", 48)
                ),
            )
            number = resolve_fuel_model_number(fuel_model)
        except (FuelMoistureError, SpreadError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        return {
            **classes,
            "fuel_model_number": number,
            "effective_moisture_pct": effective_dead_fuel_moisture(number, classes),
        }

    # --- EM-020: uncertainty display endpoints ------------------------------

    @api.post("/api/v1/spread/uncertainty", tags=["spread-uncertainty"])
    def spread_uncertainty(req: SpreadPredictRequest) -> dict[str, Any]:
        """Optimistic/expected/pessimistic envelope per horizon plus the
        model-confidence indicator from a wind-perturbed multi-run ensemble."""
        try:
            with database.session() as session:
                return uncertainty_envelope(session, settings, req.model_dump())
        except SpreadError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    # --- EM-021: natural barrier management endpoints ------------------------

    @api.post("/api/v1/spread/barriers", tags=["spread-barriers"])
    def spread_barrier_create(req: BarrierRequest) -> dict[str, Any]:
        """Register a water body (full barrier) or road/stream (slowdown)."""
        try:
            with database.session() as session:
                return register_barrier(session, req.model_dump())
        except BarrierError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/spread/barriers", tags=["spread-barriers"])
    def spread_barriers() -> dict[str, Any]:
        """List registered natural barriers, newest first."""
        with database.session() as session:
            rows = list_barriers(session)
            return {"count": len(rows), "barriers": rows}

    @api.delete("/api/v1/spread/barriers/{barrier_key}", tags=["spread-barriers"])
    def spread_barrier_delete(barrier_key: str) -> dict[str, Any]:
        """Remove one natural barrier."""
        with database.session() as session:
            removed = delete_barrier(session, barrier_key)
        if not removed:
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "error",
                    "error": f"barrier {barrier_key} not found",
                },
            )
        return {"status": "deleted", "barrier_key": barrier_key}

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

    # --- EM-018: automatic forecast trigger endpoints ----------------------

    @api.get("/api/v1/spread/trigger-status", tags=["spread-trigger"])
    def spread_trigger_status(event_key: str = Query(...)) -> dict[str, Any]:
        """Debounced trigger decision for one event (would a sweep re-run?)."""
        with database.session() as session:
            event = session.scalar(
                select(FireEvent).where(FireEvent.event_key == event_key)
            )
            if event is None:
                raise HTTPException(
                    status_code=404,
                    detail={"status": "error", "error": f"event {event_key} not found"},
                )
            return {
                "auto_trigger_enabled": bool(
                    getattr(settings, "SPREAD_AUTO_TRIGGER_ENABLED", True)
                ),
                **evaluate_trigger(session, settings, event),
            }

    @api.post("/api/v1/spread/trigger-sweep", tags=["spread-trigger"])
    def spread_trigger_sweep(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Run the debounced auto-trigger sweep on demand (ops/demo aid)."""
        with database.session() as session:
            keys = [event_key] if event_key else None
            return {
                "status": "ok",
                **auto_trigger_forecasts(session, settings, event_keys=keys),
            }
