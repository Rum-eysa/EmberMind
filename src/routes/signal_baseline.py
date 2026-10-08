"""Region communication-signal baseline endpoints (EM-035, Epic E4).

Read-only: the per-cell 30-day baseline is recomputed on each request from the
selected signal source, so nothing is written to the database. These feed the
operator map's silent-zone baseline panel.
"""

from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.signal_baseline import (
    SignalBaselineError,
    baseline_cell,
    baseline_config,
    baseline_report,
)


def _http_error(exc: SignalBaselineError) -> HTTPException:
    message = str(exc)
    status = 404 if "bilinmeyen hücre" in message else 400
    return HTTPException(
        status_code=status, detail={"status": "error", "error": message}
    )


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


def register_signal_baseline_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-035 signal-baseline feed."""
    del database  # EM-035 recomputes every baseline read-time; nothing is written.

    @api.get("/api/v1/signal-baseline/config", tags=["panel"])
    def signal_baseline_config() -> dict[str, Any]:
        """Sources (available + planned), window bounds, grid and sensitivity."""
        return baseline_config(settings)

    @api.get("/api/v1/signal-baseline", tags=["panel"])
    def signal_baseline_report(
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        window_days: int | None = Query(default=None, ge=1, le=365),
        region_key: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=500),
    ) -> dict[str, Any]:
        """Per-cell baseline + latest-reading z-score, quietest cells first."""
        stamp = _parse_as_of(as_of)
        try:
            return baseline_report(
                settings,
                source=source,
                as_of=stamp,
                window_days=window_days,
                region_key=region_key,
                limit=limit,
            )
        except SignalBaselineError as exc:
            raise _http_error(exc) from exc

    @api.get("/api/v1/signal-baseline/cells/{region_key}", tags=["panel"])
    def signal_baseline_single(
        region_key: str,
        source: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        window_days: int | None = Query(default=None, ge=1, le=365),
    ) -> dict[str, Any]:
        """Baseline for one monitored cell by key (404 if unknown)."""
        stamp = _parse_as_of(as_of)
        try:
            return baseline_cell(
                settings,
                region_key,
                source=source,
                as_of=stamp,
                window_days=window_days,
            )
        except SignalBaselineError as exc:
            raise _http_error(exc) from exc
