"""UI-authored custom scenario endpoints (EM-108, Epic E11).

Author a demo scenario from the interface (fire location, wind history, exclusion
zones), validate it through the EM-104 engine, save it into the scenario library
surface, then preview or one-click activate it exactly like an EM-105 library
scenario (the launch writes the same labelled synthetic rows plus one ``ScenarioRun``
stamped ``preset=custom:<key>``).
"""
from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.database import Database
from src.services.scenario_editor import (
    ATTRIBUTION,
    ScenarioEditorError,
    activate,
    create,
    delete,
    detail,
    editor_config,
    list_scenarios,
    preview,
    update,
)


class ScenarioAuthorRequest(BaseModel):
    """Author a new custom scenario definition."""

    model_config = {"protected_namespaces": ()}

    key: str
    title: str
    seed: int
    description: str | None = None
    config: dict[str, Any] = {}
    created_by: str | None = None


class ScenarioEditRequest(BaseModel):
    """Edit an existing custom scenario (only provided fields change)."""

    model_config = {"protected_namespaces": ()}

    title: str | None = None
    description: str | None = None
    seed: int | None = None
    config: dict[str, Any] | None = None


def _raise(exc: ScenarioEditorError) -> NoReturn:
    """Map a service error to 404 (missing key) or 400 (validation)."""
    text = str(exc).lower()
    status = 404 if "not found" in text else 400
    raise HTTPException(
        status_code=status, detail={"status": "error", "error": str(exc)}
    ) from exc


def register_scenario_editor_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-108 custom scenario-editor endpoints."""

    @api.get("/api/v1/scenarios/custom/config", tags=["scenario-editor"])
    def custom_config() -> dict[str, Any]:
        """Editor descriptor: caps, validation guarantees, reserved keys."""
        return editor_config(settings)

    # Registered before "/{key}" so the literal "config" is not read as a key.
    @api.get("/api/v1/scenarios/custom", tags=["scenario-editor"])
    def custom_list() -> dict[str, Any]:
        """Authored scenarios, newest first (added alongside the library)."""
        with database.session() as session:
            items = list_scenarios(session)
        return {
            "count": len(items),
            "scenarios": items,
            "attribution": ATTRIBUTION,
        }

    @api.post("/api/v1/scenarios/custom", tags=["scenario-editor"])
    def custom_create(req: ScenarioAuthorRequest) -> dict[str, Any]:
        """Validate and save a new authored scenario."""
        try:
            with database.session() as session:
                row = create(
                    session,
                    settings,
                    key=req.key,
                    title=req.title,
                    description=req.description,
                    seed=req.seed,
                    config=req.config,
                    created_by=req.created_by,
                )
                session.commit()
        except ScenarioEditorError as exc:
            _raise(exc)
        return {"status": "created", "scenario": row}

    @api.get("/api/v1/scenarios/custom/{key}", tags=["scenario-editor"])
    def custom_detail(key: str) -> dict[str, Any]:
        """Fetch one authored scenario including its normalized config."""
        try:
            with database.session() as session:
                return {"scenario": detail(session, key)}
        except ScenarioEditorError as exc:
            _raise(exc)

    @api.patch("/api/v1/scenarios/custom/{key}", tags=["scenario-editor"])
    def custom_update(key: str, req: ScenarioEditRequest) -> dict[str, Any]:
        """Edit an authored scenario in place."""
        try:
            with database.session() as session:
                row = update(
                    session,
                    key,
                    title=req.title,
                    description=req.description,
                    seed=req.seed,
                    config=req.config,
                )
                session.commit()
        except ScenarioEditorError as exc:
            _raise(exc)
        return {"status": "updated", "scenario": row}

    @api.delete("/api/v1/scenarios/custom/{key}", tags=["scenario-editor"])
    def custom_delete(key: str) -> dict[str, Any]:
        """Remove an authored scenario definition."""
        try:
            with database.session() as session:
                result = delete(session, key)
                session.commit()
        except ScenarioEditorError as exc:
            _raise(exc)
        return result

    @api.get("/api/v1/scenarios/custom/{key}/preview", tags=["scenario-editor"])
    def custom_preview(key: str) -> dict[str, Any]:
        """Build the scenario dataset (nothing persisted)."""
        try:
            with database.session() as session:
                return preview(session, key)
        except ScenarioEditorError as exc:
            _raise(exc)

    @api.post("/api/v1/scenarios/custom/{key}/activate", tags=["scenario-editor"])
    def custom_activate(key: str) -> dict[str, Any]:
        """One-click start: generate + persist the authored scenario."""
        try:
            with database.session() as session:
                result = activate(session, key)
                session.commit()
        except ScenarioEditorError as exc:
            _raise(exc)
        return result
