"""High-priority silent-region alert endpoints (EM-040, Epic E4).

Read-only: the alert feed is regenerated from EM-037's graded report on each
request, so nothing is written to the database. These feed the operator map's
"sessiz bölge uyarıları" panel.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.silent_region_alert import (
    SilentRegionAlertError,
    silent_region_alert_config,
    silent_region_alert_report,
)


def register_silent_region_alert_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-040 silent-region alert feed."""

    @api.get("/api/v1/silent-region-alerts/config", tags=["panel"])
    def silent_region_alert_config_endpoint() -> dict[str, Any]:
        """Risk-level ladder, its bands, the suppression rule and persistence."""
        return silent_region_alert_config(settings)

    @api.get("/api/v1/silent-region-alerts", tags=["panel"])
    def silent_region_alert_report_endpoint(
        level: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        """High-priority silent-region alerts, de-duplicated per region."""
        try:
            with database.session() as session:
                return silent_region_alert_report(
                    session, settings, level=level, limit=limit
                )
        except SilentRegionAlertError as exc:
            raise HTTPException(
                status_code=400, detail={"status": "error", "error": str(exc)}
            ) from exc
