"""Seasonally-adjusted signal baseline endpoints (EM-043, Epic E4).

Read-only: each cell's hour-of-day / day-of-week seasonal baseline is recomputed
from the selected source on every request, so nothing is written to the database.
These feed the operator map's seasonal-baseline panel and expose the flat-vs-
seasonal false-alarm comparison and the daily-refresh recompute.
"""
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.signal_baseline_seasonal import (
    SignalSeasonalError,
    refresh_daily_baselines,
    seasonal_baseline_config,
    seasonal_report,
)


def _http_error(exc: SignalSeasonalError) -> HTTPException:
    message = str(exc)
    return HTTPException(status_code=400, detail={"status": "error", "error": message})


def _parse_as_of(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error": "as_of YYYY-MM-DD biçiminde olmalı"},
        ) from exc


def register_signal_baseline_seasonal_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-043 seasonal-baseline feed."""
    del database  # EM-043 recomputes every seasonal baseline read-time; nothing is written.

    @api.get("/api/v1/signal-baseline-seasonal/config", tags=["panel"])
    def signal_baseline_seasonal_config() -> dict[str, Any]:
        """Sources, seasonal dimensions, hour/weekday catalogue, bounds, refresh."""
        return seasonal_baseline_config(settings)

    @api.get("/api/v1/signal-baseline-seasonal", tags=["panel"])
    # pylint: disable-next=too-many-arguments  # six validated read-only query knobs
    def signal_baseline_seasonal_report(
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        window_days: int | None = Query(default=None, ge=1, le=365),
        hour: int | None = Query(default=None, ge=0, le=23),
        region_key: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=500),
    ) -> dict[str, Any]:
        """Per-cell seasonal vs flat scores + false-alarm reduction summary."""
        stamp = _parse_as_of(as_of)
        try:
            return seasonal_report(
                settings,
                source=source,
                as_of=stamp,
                window_days=window_days,
                hour=hour,
                region_key=region_key,
                limit=limit,
            )
        except SignalSeasonalError as exc:
            raise _http_error(exc) from exc

    @api.get("/api/v1/signal-baseline-seasonal/refresh", tags=["panel"])
    def signal_baseline_seasonal_refresh(
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        window_days: int | None = Query(default=None, ge=1, le=365),
        hour: int | None = Query(default=None, ge=0, le=23),
    ) -> dict[str, Any]:
        """Recompute every cell's seasonal baseline as of the requested date."""
        stamp = _parse_as_of(as_of)
        try:
            return refresh_daily_baselines(
                settings,
                source=source,
                as_of=stamp,
                window_days=window_days,
                hour=hour,
            )
        except SignalSeasonalError as exc:
            raise _http_error(exc) from exc
