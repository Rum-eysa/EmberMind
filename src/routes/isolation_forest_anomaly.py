"""Isolation Forest silent-zone anomaly endpoints (EM-036, Epic E4).

Read-only: each cell's learned anomaly score and the configurable ``mean - sigma
* std`` quiet test are recomputed from the selected signal source on every
request, so nothing is written to the database. These feed the operator map's
anomaly-scoring panel and expose the real-time (15-min cadence) sweep that the
Celery beat drives.
"""

from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.routes._common import parse_as_of as _parse_as_of
from src.services.isolation_forest_anomaly import (
    IsolationForestAnomalyError,
    anomaly_config,
    anomaly_report,
    score_silent_zone_anomalies,
)


def _http_error(exc: IsolationForestAnomalyError) -> HTTPException:
    message = str(exc)
    return HTTPException(status_code=400, detail={"status": "error", "error": message})


def register_isolation_forest_anomaly_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-036 anomaly-scoring feed."""
    del database  # EM-036 recomputes every anomaly score read-time; nothing is written.

    @api.get("/api/v1/isolation-forest-anomaly/config", tags=["panel"])
    def isolation_forest_anomaly_config() -> dict[str, Any]:
        """Sources, model knobs, sigma/window bounds, real-time cadence."""
        return anomaly_config(settings)

    @api.get("/api/v1/isolation-forest-anomaly", tags=["panel"])
    # pylint: disable-next=too-many-arguments  # six validated read-only query knobs
    def isolation_forest_anomaly_report(
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        window_days: int | None = Query(default=None, ge=1, le=365),
        sigma_multiplier: float | None = Query(default=None, ge=1.0, le=5.0),
        region_key: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=500),
    ) -> dict[str, Any]:
        """Per-cell learned anomaly score + configurable-threshold quiet test."""
        stamp = _parse_as_of(as_of)
        try:
            return anomaly_report(
                settings,
                source=source,
                as_of=stamp,
                window_days=window_days,
                sigma_multiplier=sigma_multiplier,
                region_key=region_key,
                limit=limit,
            )
        except IsolationForestAnomalyError as exc:
            raise _http_error(exc) from exc

    @api.get("/api/v1/isolation-forest-anomaly/latest", tags=["panel"])
    def isolation_forest_anomaly_latest(
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        window_days: int | None = Query(default=None, ge=1, le=365),
        sigma_multiplier: float | None = Query(default=None, ge=1.0, le=5.0),
    ) -> dict[str, Any]:
        """Produce the current real-time snapshot (what the 15-min beat drives)."""
        stamp = _parse_as_of(as_of)
        try:
            return score_silent_zone_anomalies(
                settings,
                source=source,
                as_of=stamp,
                window_days=window_days,
                sigma_multiplier=sigma_multiplier,
            )
        except IsolationForestAnomalyError as exc:
            raise _http_error(exc) from exc
