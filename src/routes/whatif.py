"""Wind what-if & dynamic recompute endpoints (EM-055, Epic E6).

Let an operator ask "what if the wind rotated 45 degrees?" and get the fresh
risk zones, capacity gap and threat recommendations back in seconds, with the
original and the scenario side by side. The recompute is ephemeral: nothing is
written to the database (see services.whatif).
"""
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.database import Database
from src.services.capacity_whatif import (
    CAPACITY_WHATIF_ATTRIBUTION,
    CapacityWhatIfError,
    run_capacity_whatif,
)
from src.services.perf_budget import (
    record_recompute_latency,
    resolve_recompute_settings,
)
from src.services.risk_index import RiskIndexError
from src.services.spread import SpreadError
from src.services.whatif import (
    WHATIF_ATTRIBUTION,
    WhatIfError,
    recompute_target_seconds,
    run_whatif,
)


class WhatIfRequest(BaseModel):
    """Wind what-if inputs; omit wind knobs to only change rotation/factor."""

    model_config = {"protected_namespaces": ()}

    latitude: float
    longitude: float
    event_key: str | None = None
    wind_rotation_delta_deg: float | None = None
    wind_speed_factor: float | None = None
    wind_from_deg: float | None = None
    wind_speed_kmh: float | None = None
    air_temp_c: float | None = None
    relative_humidity_pct: float | None = None
    fuel_moisture_pct: float | None = None
    slope_deg: float | None = None
    aspect_deg: float | None = None
    fuel_model: str | None = None
    horizon_minutes: list[int] | None = None


class WhatIfCapacityRequest(BaseModel):
    """Capacity what-if: extra units per type, optionally scoped to one event."""

    model_config = {"protected_namespaces": ()}

    added_resources: dict[str, int] = {}
    event_key: str | None = None


def register_whatif_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the wind what-if recompute endpoints."""

    @api.get("/api/v1/whatif/config", tags=["whatif"])
    def whatif_config() -> dict[str, Any]:
        """Recompute target budget the UI advertises for a what-if refresh."""
        return {
            "whatif": "wind",
            "target_seconds": recompute_target_seconds(settings),
            "persistence": "none",
            "attribution": WHATIF_ATTRIBUTION,
            "capacity_attribution": CAPACITY_WHATIF_ATTRIBUTION,
        }

    @api.post("/api/v1/whatif/wind", tags=["whatif"])
    def whatif_wind(req: WhatIfRequest) -> dict[str, Any]:
        """Recompute risk zones, capacity gap and recommendations for a
        wind direction/speed change; original and scenario compared live.

        EM-060: the recompute consults the rolling p95 budget and, when it is
        over target, automatically runs at a coarse resolution; the measured
        duration is fed back as a latency sample (telemetry only, no forecast
        is persisted).
        """
        try:
            with database.session() as session:
                run_settings, resolution = resolve_recompute_settings(session, settings)
                result = run_whatif(session, run_settings, req.model_dump())
                status = record_recompute_latency(
                    session, settings, result["compute_ms"], "whatif_wind", resolution
                )
                result["perf_budget"] = {
                    "resolution": resolution,
                    "p95_ms": status["p95_ms"],
                    "within_budget": status["within_budget"],
                    "scale_down_active": status["scale_down_active"],
                }
                return result
        except (WhatIfError, SpreadError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.post("/api/v1/whatif/capacity", tags=["whatif"])
    def whatif_capacity(req: WhatIfCapacityRequest) -> dict[str, Any]:
        """Re-price each event's spread demand against reinforced capacity.

        EM-056: keeps the forecast fixed and adds hypothetical units (crew /
        helicopter / uav) to the live effective capacity, reporting the gap
        change and which incidents the reinforcement resolves. Ephemeral.
        """
        try:
            with database.session() as session:
                return run_capacity_whatif(
                    session, settings, req.added_resources, req.event_key
                )
        except (CapacityWhatIfError, RiskIndexError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
