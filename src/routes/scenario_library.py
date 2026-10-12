"""Ready-made demo scenario library endpoints (EM-105, Epic E11).

Curated, deterministic scenarios built on the EM-104 generator: list the
library, preview one scenario, then one-click *activate* (persist) or *replay*
(rewind + relaunch). Activation writes the same labelled synthetic rows and one
``ScenarioRun`` audit row (stamped ``preset=library:<key>``) as EM-104.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.scenario_library import (
    ScenarioLibraryError,
    activate,
    activated_runs,
    library_config,
    preview,
    replay,
)
from src.services.synthetic import SyntheticError


def _not_found(exc: ScenarioLibraryError) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"status": "not_found", "error": str(exc)}
    )


def _bad_request(exc: SyntheticError) -> HTTPException:
    return HTTPException(status_code=400, detail={"status": "error", "error": str(exc)})


def register_scenario_library_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-105 demo scenario-library endpoints."""

    @api.get("/api/v1/scenarios/library", tags=["scenario-library"])
    def library() -> dict[str, Any]:
        """The curated scenario catalog plus the launch guarantees."""
        return library_config(settings)

    # Registered before "/{key}" so the literal "runs" is not read as a key.
    @api.get("/api/v1/scenarios/library/runs", tags=["scenario-library"])
    def runs(
        key: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        """Recent library activations (optionally scoped to one scenario)."""
        try:
            with database.session() as session:
                items = [run.as_dict for run in activated_runs(session, key, limit)]
        except ScenarioLibraryError as exc:
            raise _not_found(exc) from exc
        return {"count": len(items), "runs": items}

    @api.get("/api/v1/scenarios/library/{key}", tags=["scenario-library"])
    def scenario_detail(key: str) -> dict[str, Any]:
        """Preview one scenario (dataset built, nothing persisted)."""
        try:
            return preview(key, settings)
        except ScenarioLibraryError as exc:
            raise _not_found(exc) from exc
        except SyntheticError as exc:
            raise _bad_request(exc) from exc

    @api.post("/api/v1/scenarios/library/{key}/activate", tags=["scenario-library"])
    def scenario_activate(key: str) -> dict[str, Any]:
        """One-click start: generate + persist the scenario."""
        try:
            with database.session() as session:
                result = activate(session, key, settings)
                session.commit()
        except ScenarioLibraryError as exc:
            raise _not_found(exc) from exc
        except SyntheticError as exc:
            raise _bad_request(exc) from exc
        return result

    @api.post("/api/v1/scenarios/library/{key}/replay", tags=["scenario-library"])
    def scenario_replay(key: str) -> dict[str, Any]:
        """Rewind the scenario's rows and relaunch it deterministically."""
        try:
            with database.session() as session:
                result = replay(session, key, settings)
                session.commit()
        except ScenarioLibraryError as exc:
            raise _not_found(exc) from exc
        except SyntheticError as exc:
            raise _bad_request(exc) from exc
        return result
