"""Scenario playback control endpoints (EM-107, Epic E11).

Drive a launched demo scenario's timeline: read the frame sequence, get the
wall-clock playback schedule for a chosen speed factor (play / pause / speed),
and resolve the current frame from elapsed wall time. Everything is projected
at read time from the EM-104/EM-105 dataset — no state is persisted.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.scenario_library import ScenarioLibraryError
from src.services.scenario_playback import (
    ScenarioPlaybackError,
    frame_at,
    playback_config,
    playback_plan,
    timeline_frames,
)


def _not_found(exc: ScenarioLibraryError) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"status": "not_found", "error": str(exc)}
    )


def _bad_request(exc: ScenarioPlaybackError) -> HTTPException:
    return HTTPException(status_code=400, detail={"status": "error", "error": str(exc)})


def register_scenario_playback_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-107 scenario-playback endpoints."""
    del database  # playback is read-only over the generator; no session needed

    @api.get("/api/v1/scenarios/playback/config", tags=["scenario-playback"])
    def config() -> dict[str, Any]:
        """The playback knobs (speed range, frame interval, controls)."""
        return playback_config(settings)

    @api.get("/api/v1/scenarios/playback/{key}/frames", tags=["scenario-playback"])
    def frames(key: str) -> dict[str, Any]:
        """The scenario's ordered playback frames (nothing persisted)."""
        try:
            return timeline_frames(key, settings)
        except ScenarioLibraryError as exc:
            raise _not_found(exc) from exc
        except ScenarioPlaybackError as exc:
            raise _bad_request(exc) from exc

    @api.get("/api/v1/scenarios/playback/{key}/plan", tags=["scenario-playback"])
    def plan(
        key: str,
        speed_factor: float | None = Query(default=None, gt=0.0, le=8.0),
    ) -> dict[str, Any]:
        """Wall-clock playback schedule for one scenario at a speed factor."""
        try:
            return playback_plan(key, settings, speed_factor)
        except ScenarioLibraryError as exc:
            raise _not_found(exc) from exc
        except ScenarioPlaybackError as exc:
            raise _bad_request(exc) from exc

    @api.get("/api/v1/scenarios/playback/{key}/cursor", tags=["scenario-playback"])
    def cursor(
        key: str,
        elapsed_seconds: float = Query(default=0.0, ge=0.0),
        speed_factor: float | None = Query(default=None, gt=0.0, le=8.0),
    ) -> dict[str, Any]:
        """Resolve the current frame for an elapsed wall-clock time."""
        try:
            return frame_at(key, settings, elapsed_seconds, speed_factor)
        except ScenarioLibraryError as exc:
            raise _not_found(exc) from exc
        except ScenarioPlaybackError as exc:
            raise _bad_request(exc) from exc
