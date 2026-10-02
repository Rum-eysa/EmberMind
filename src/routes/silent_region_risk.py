"""High-priority silent-region risk endpoints (EM-037, Epic E4).

Read-only: silent regions are graded against the active fires' spread-forecast
polygons on each request, so nothing is written to the database. These feed the
operator map's "yüksek öncelikli sessiz bölge" panel.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.silent_region_risk import (
    SilentRegionRiskError,
    silent_region_risk_config,
    silent_region_risk_report,
)


def register_silent_region_risk_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-037 silent-region risk feed."""

    @api.get("/api/v1/silent-region-risk/config", tags=["panel"])
    def silent_region_risk_config_endpoint() -> dict[str, Any]:
        """Thresholds, the risk x silence derivation and its persistence."""
        return silent_region_risk_config(settings)

    @api.get("/api/v1/silent-region-risk", tags=["panel"])
    def silent_region_risk_report_endpoint(
        flagged_only: bool = Query(default=False),
        limit: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        """Silent regions by forecast-reach risk x silence, most urgent first."""
        try:
            with database.session() as session:
                return silent_region_risk_report(
                    session, settings, flagged_only=flagged_only, limit=limit
                )
        except SilentRegionRiskError as exc:
            raise HTTPException(
                status_code=400, detail={"status": "error", "error": str(exc)}
            ) from exc
