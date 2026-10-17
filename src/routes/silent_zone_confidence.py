"""Silent-zone confidence labelling endpoints (EM-038, Epic E4).

Read-only: the false-alarm confidence ladder is derived on each request from the
EM-035 per-cell baseline (no DB access, nothing is written). These feed the
operator map's "yanlış alarm önleme" confidence panel.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.routes._common import parse_as_of as _parse_as_of
from src.services.silent_zone_confidence import (
    SilentZoneConfidenceError,
    silent_zone_confidence_config,
    silent_zone_confidence_report,
)


def register_silent_zone_confidence_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-038 silent-zone confidence feed."""
    del database  # EM-038 is a pure read-time projection over EM-035.

    @api.get("/api/v1/silent-zone-confidence/config", tags=["panel"])
    def silent_zone_confidence_config_endpoint() -> dict[str, Any]:
        """The confidence ladder, its rules and thresholds."""
        return silent_zone_confidence_config(settings)

    @api.get("/api/v1/silent-zone-confidence", tags=["panel"])
    def silent_zone_confidence_report_endpoint(
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        window_days: int | None = Query(default=None, ge=1, le=365),
        confidence: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        """Silent candidates labelled high/medium/low confidence, most urgent first."""
        stamp = _parse_as_of(as_of)
        try:
            return silent_zone_confidence_report(
                settings,
                source=source,
                as_of=stamp,
                window_days=window_days,
                confidence=confidence,
                limit=limit,
            )
        except SilentZoneConfidenceError as exc:
            raise HTTPException(
                status_code=400, detail={"status": "error", "error": str(exc)}
            ) from exc
