"""External support early-forecast endpoints (EM-065, Epic E7).

A read-only projection over the EM-030/EM-033 capacity-gap timeline: warn the
cross-border coordinator, before the gap actually opens, that national capacity
will run short at ``T+X`` minutes and how many reinforcement units (``~ Y``)
that implies. Nothing is persisted.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.external_support import (
    EX_SUPPORT_ATTRIBUTION,
    forecast_external_support,
)
from src.services.risk_index import RiskIndexError


def register_external_support_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-065 external-support forecast feed."""

    @api.get("/api/v1/external-support", tags=["panel"])
    def external_support(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Early forecast of national-capacity shortfall and support units."""
        try:
            with database.session() as session:
                return forecast_external_support(session, settings, event_key)
        except RiskIndexError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/external-support/config", tags=["panel"])
    def external_support_config() -> dict[str, Any]:
        """The per-unit reinforcement capacity and lead-time the forecast uses."""
        return {
            "support_unit_ha_per_hour": float(
                getattr(settings, "EXTERNAL_SUPPORT_UNIT_HA_PER_HOUR", 12.0)
            ),
            "lead_time_minutes": int(
                getattr(settings, "EXTERNAL_SUPPORT_LEAD_TIME_MINUTES", 60)
            ),
            "horizon_minutes": list(
                getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
            ),
            "attribution": EX_SUPPORT_ATTRIBUTION,
            "persistence": "none",
        }
