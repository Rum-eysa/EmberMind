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
        }

    @api.post("/api/v1/whatif/wind", tags=["whatif"])
    def whatif_wind(req: WhatIfRequest) -> dict[str, Any]:
        """Recompute risk zones, capacity gap and recommendations for a
        wind direction/speed change; original and scenario compared live."""
        try:
            with database.session() as session:
                return run_whatif(session, settings, req.model_dump())
        except (WhatIfError, SpreadError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
