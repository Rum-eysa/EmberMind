"""Recompute performance budget endpoints (EM-060, Epic E6).

Expose the rolling p95 recompute-latency read-out so the operator can see
whether recomputes are meeting the 10-second budget and whether the automatic
coarse-resolution scale-down is engaged, plus the coarse-resolution knobs and
a manual telemetry sink for load tests / operations.
"""
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.database import Database
from src.services.perf_budget import (
    PERF_BUDGET_ATTRIBUTION,
    RESOLUTION_COARSE,
    RESOLUTION_FINE,
    budget_status,
    next_resolution,
    record_recompute_latency,
)


class LatencySampleRequest(BaseModel):
    """Manual recompute-latency telemetry sample (load test / operations)."""

    latency_ms: float
    source: str = "manual"
    resolution: str = RESOLUTION_FINE


def register_perf_budget_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the recompute performance-budget endpoints."""

    @api.get("/api/v1/perf-budget", tags=["perf-budget"])
    def perf_budget_status() -> dict[str, Any]:
        """Rolling p95 recompute latency against the operator budget."""
        with database.session() as session:
            return budget_status(session, settings)

    @api.get("/api/v1/perf-budget/config", tags=["perf-budget"])
    def perf_budget_config() -> dict[str, Any]:
        """Budget target, window and the coarse-resolution scale-down knobs."""
        with database.session() as session:
            status: dict[str, Any] = dict(budget_status(session, settings))
            status["panel"] = "perf_budget_config"
            status["attribution"] = PERF_BUDGET_ATTRIBUTION
            status["next_resolution"] = next_resolution(session, settings)
        return status

    @api.post("/api/v1/perf-budget/sample", tags=["perf-budget"])
    def perf_budget_sample(req: LatencySampleRequest) -> dict[str, Any]:
        """Record one recompute latency and return the refreshed budget state."""
        if req.latency_ms < 0:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": "latency_ms must be >= 0"},
            )
        resolution = (
            RESOLUTION_COARSE
            if str(req.resolution).strip().lower() == RESOLUTION_COARSE
            else RESOLUTION_FINE
        )
        with database.session() as session:
            return record_recompute_latency(
                session, settings, req.latency_ms, req.source, resolution
            )
