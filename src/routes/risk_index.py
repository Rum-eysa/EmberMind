"""Operational risk index endpoints (EM-029, Epic E3)."""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.risk_index import (
    RISK_ATTRIBUTION,
    RISK_LEVELS,
    RiskIndexError,
    compute_risk_index,
    level_thresholds,
)


def register_risk_index_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the per-horizon operational risk index feed."""

    @api.get("/api/v1/risk-index/config", tags=["panel"])
    def risk_index_config() -> dict[str, Any]:
        """The configurable severity band boundaries and the level order."""
        return {
            "thresholds": level_thresholds(settings),
            "levels": list(RISK_LEVELS),
            "horizon_minutes": list(
                getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
            ),
            "attribution": RISK_ATTRIBUTION,
        }

    @api.get("/api/v1/risk-index", tags=["panel"])
    def risk_index(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Risk(t) per horizon for every active event (or one event)."""
        try:
            with database.session() as session:
                return compute_risk_index(session, settings, event_key)
        except RiskIndexError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "error": str(exc)},
            ) from exc
