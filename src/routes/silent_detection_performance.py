"""Silent-region detection performance endpoints (EM-042, Epic E4).

Read-only: the synthetic-scenario performance report is regenerated and
re-scored on each request (no DB access, nothing is written). These feed the
operator map's "sessiz bölge performans" measurement panel.
"""
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.silent_detection_performance import (
    SilentDetectionPerformanceError,
    evaluate_detection,
    performance_config,
)


def _parse_reference(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error": "as_of YYYY-MM-DD biçiminde olmalı"},
        ) from exc


def register_silent_detection_performance_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-042 silent-region detection performance feed."""
    del database  # EM-042 is a pure read-time synthetic-scenario evaluation.

    @api.get("/api/v1/silent-detection-performance/config", tags=["panel"])
    def silent_detection_performance_config_endpoint() -> dict[str, Any]:
        """The scenario knobs, bounds and metric catalogue."""
        return performance_config(settings)

    @api.get("/api/v1/silent-detection-performance", tags=["panel"])
    # pylint: disable-next=too-many-arguments  # six validated read-only query knobs
    def silent_detection_performance_endpoint(
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        horizon_days: int | None = Query(default=None, ge=1, le=365),
        window_days: int | None = Query(default=None, ge=1, le=120),
        onset_rate: float | None = Query(default=None, ge=0.0, le=1.0),
        sensitivity_z: float | None = Query(default=None, gt=0.0),
    ) -> dict[str, Any]:
        """TPR / FPR / precision / F1 and alert delay for the synthetic scenario."""
        reference = _parse_reference(as_of)
        try:
            return evaluate_detection(
                settings,
                source=source,
                reference=reference,
                horizon_days=horizon_days,
                baseline_window_days=window_days,
                onset_rate=onset_rate,
                sensitivity_z=sensitivity_z,
            )
        except SilentDetectionPerformanceError as exc:
            raise HTTPException(
                status_code=400, detail={"status": "error", "error": str(exc)}
            ) from exc
