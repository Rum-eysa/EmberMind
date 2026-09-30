"""Saved/shareable what-if scenario endpoints (EM-059, Epic E6).

Persistence + share links for the ephemeral what-if runs. A scenario only holds
its inputs; replaying them through ``/whatif/wind`` or ``/whatif/capacity``
produces a fresh result. Sharing mints an opaque token so a coordinator can hand
a scenario to a teammate (``/by-token/<token>``) who can load and replay it.
"""
from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.scenario_share import (
    ScenarioError,
    create_scenario,
    delete_scenario,
    disable_share,
    enable_share,
    get_by_share_token,
    get_scenario,
    list_scenarios,
    rename_scenario,
)

_SCENARIO_ATTRIBUTION = "Kaydedilen/paylaşılan what-if senaryoları: EM-059"


class ScenarioCreateRequest(BaseModel):
    """Name a what-if scenario and store its inputs for later replay/share."""

    model_config = {"protected_namespaces": ()}

    name: str
    kind: str
    params: dict[str, Any] = {}
    event_key: str | None = None
    created_by: str | None = None
    notes: str | None = None


class ScenarioRenameRequest(BaseModel):
    """Rename a saved scenario."""

    name: str


def _raise(exc: ScenarioError) -> NoReturn:
    """Map a service error to the right HTTP status (404 missing, else 400)."""
    text = str(exc).lower()
    status = (
        404 if ("not found" in text or "invalid" in text or "revoked" in text) else 400
    )
    raise HTTPException(
        status_code=status, detail={"status": "error", "error": str(exc)}
    ) from exc


def register_scenario_share_routes(
    api: FastAPI, database: Database, _settings: Any
) -> None:
    """Attach the EM-059 scenario save/share endpoints."""

    @api.get("/api/v1/whatif/scenarios/config", tags=["scenarios"])
    def scenario_config() -> dict[str, Any]:
        """Feature descriptor for the saved-scenario panel."""
        return {
            "scenarios": "whatif",
            "kinds": ["wind", "capacity"],
            "persistence": "inputs only (results replayed live)",
            "sharing": "opaque token link",
            "attribution": _SCENARIO_ATTRIBUTION,
        }

    @api.post("/api/v1/whatif/scenarios", tags=["scenarios"])
    def scenario_create(req: ScenarioCreateRequest) -> dict[str, Any]:
        """Save a named what-if scenario (its inputs) for reuse and sharing."""
        try:
            with database.session() as session:
                scenario = create_scenario(
                    session,
                    name=req.name,
                    kind=req.kind,
                    params=req.params,
                    event_key=req.event_key,
                    created_by=req.created_by,
                    notes=req.notes,
                )
                session.commit()
                return {"status": "created", "scenario": scenario}
        except ScenarioError as exc:
            _raise(exc)

    @api.get("/api/v1/whatif/scenarios", tags=["scenarios"])
    def scenario_list(
        kind: str | None = Query(default=None),
        event_key: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        """List saved scenarios, newest first, optionally filtered."""
        with database.session() as session:
            rows = list_scenarios(session, kind=kind, event_key=event_key, limit=limit)
        return {
            "count": len(rows),
            "scenarios": rows,
            "attribution": _SCENARIO_ATTRIBUTION,
        }

    @api.get("/api/v1/whatif/scenarios/by-token/{token}", tags=["scenarios"])
    def scenario_by_token(token: str) -> dict[str, Any]:
        """Fetch a shared scenario through its opaque token (team hand-off)."""
        with database.session() as session:
            try:
                return {"scenario": get_by_share_token(session, token)}
            except ScenarioError as exc:
                _raise(exc)

    @api.get("/api/v1/whatif/scenarios/{scenario_key}", tags=["scenarios"])
    def scenario_get(scenario_key: str) -> dict[str, Any]:
        """Fetch one saved scenario by key."""
        with database.session() as session:
            try:
                return {"scenario": get_scenario(session, scenario_key)}
            except ScenarioError as exc:
                _raise(exc)

    @api.patch("/api/v1/whatif/scenarios/{scenario_key}", tags=["scenarios"])
    def scenario_rename(
        scenario_key: str, req: ScenarioRenameRequest
    ) -> dict[str, Any]:
        """Rename a saved scenario."""
        with database.session() as session:
            try:
                scenario = rename_scenario(session, scenario_key, req.name)
                session.commit()
                return {"status": "renamed", "scenario": scenario}
            except ScenarioError as exc:
                _raise(exc)

    @api.post("/api/v1/whatif/scenarios/{scenario_key}/share", tags=["scenarios"])
    def scenario_share(scenario_key: str) -> dict[str, Any]:
        """Publish a scenario's share link (mints a token if not already shared)."""
        with database.session() as session:
            try:
                payload = enable_share(session, scenario_key)
                session.commit()
                return {"status": "shared", "scenario": payload}
            except ScenarioError as exc:
                _raise(exc)

    @api.delete("/api/v1/whatif/scenarios/{scenario_key}/share", tags=["scenarios"])
    def scenario_unshare(scenario_key: str) -> dict[str, Any]:
        """Revoke a scenario's share link."""
        with database.session() as session:
            try:
                payload = disable_share(session, scenario_key)
                session.commit()
                return {"status": "unshared", "scenario": payload}
            except ScenarioError as exc:
                _raise(exc)

    @api.delete("/api/v1/whatif/scenarios/{scenario_key}", tags=["scenarios"])
    def scenario_delete(scenario_key: str) -> dict[str, Any]:
        """Delete a saved scenario."""
        with database.session() as session:
            removed = delete_scenario(session, scenario_key)
            session.commit()
        if not removed:
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "not_found",
                    "error": f"scenario {scenario_key} not found",
                },
            )
        return {"status": "deleted", "scenario_key": scenario_key}
