"""Operator decision endpoints for positioning proposals (EM-047, Epic E5).

Three actions on a proposal — accept, edit (an accept with overrides) and reject
— so the final call stays with the operator. Accepting commits the resource to
the "yolda" (``en_route``) status; a reject records an optional reason; every
decision is written to the audit trail.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.models.recommendation import DECISION_ACTIONS
from src.services.recommendation_decision import (
    ConflictError,
    DecisionError,
    get_decision,
    list_active_assignments,
    list_decisions,
    record_decision,
    release_assignment,
    release_completed_assignments,
)

_DECISION_ATTRIBUTION = "Öneri üzerinde operatör kararı (kabul/ret/düzenleme): EM-047"
_ASSIGN_ATTRIBUTION = (
    "Çifte atama / kaynak çakışma önleme ve görev bitişi otomatik müsaite alma: "
    "EM-053"
)


class DecisionRequest(BaseModel):
    """One operator decision on a positioning proposal."""

    model_config = {"protected_namespaces": ()}

    resource_key: str
    action: str
    event_key: str | None = None
    proposal_id: str | None = None
    reason: str | None = None
    decided_by: str | None = None
    detail: dict[str, Any] | None = None
    arrival_minutes: float | None = None


class ReleaseRequest(BaseModel):
    """Free a committed unit back to ``available`` (EM-053 task completion)."""

    resource_key: str
    event_key: str | None = None
    decided_by: str | None = None
    reason: str | None = None


def _http_error(exc: DecisionError) -> HTTPException:
    """Map a service error to the right HTTP status (missing vs invalid)."""
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(
        status_code=status, detail={"status": "error", "error": str(exc)}
    )


def register_recommendation_routes(
    api: FastAPI, database: Database, _settings: Any
) -> None:
    """Attach the EM-047 recommendation-decision endpoints."""

    @api.get("/api/v1/recommendations/decisions/config", tags=["recommendations"])
    def decision_config() -> dict[str, Any]:
        """Descriptor for the operator decision workflow."""
        return {
            "actions": list(DECISION_ACTIONS),
            "commit_status": "en_route",
            "reject_reason_required": False,
            "audit": "every decision is persisted",
            "attribution": _DECISION_ATTRIBUTION,
            "conflict_prevention": {
                "single_active_assignment": True,
                "busy_statuses": ["en_route", "deployed"],
                "conflict_http_status": 409,
                "auto_release_on_completion": True,
                "attribution": _ASSIGN_ATTRIBUTION,
            },
        }

    @api.post("/api/v1/recommendations/decisions", tags=["recommendations"])
    def decision_record(req: DecisionRequest) -> dict[str, Any]:
        """Record an accept/edit/reject decision and apply its status effect."""
        try:
            with database.session() as session:
                result = record_decision(
                    session,
                    resource_key=req.resource_key,
                    action=req.action,
                    event_key=req.event_key,
                    proposal_id=req.proposal_id,
                    reason=req.reason,
                    decided_by=req.decided_by,
                    detail=req.detail,
                    arrival_minutes=req.arrival_minutes,
                )
                session.commit()
        except ConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "conflict", "error": str(exc)},
            ) from exc
        except DecisionError as exc:
            raise _http_error(exc) from exc
        return {"status": "recorded", **result, "attribution": _DECISION_ATTRIBUTION}

    @api.get("/api/v1/recommendations/decisions", tags=["recommendations"])
    def decision_list(
        event_key: str | None = Query(default=None),
        resource_key: str | None = Query(default=None),
        action: str | None = Query(default=None),
        limit_n: int = Query(default=50, ge=1, le=200, alias="limit"),
    ) -> dict[str, Any]:
        """List recorded decisions (newest first), optionally filtered."""
        with database.session() as session:
            rows = list_decisions(
                session,
                event_key=event_key,
                resource_key=resource_key,
                action=action,
                limit=limit_n,
            )
        return {
            "count": len(rows),
            "decisions": rows,
            "attribution": _DECISION_ATTRIBUTION,
        }

    @api.get(
        "/api/v1/recommendations/decisions/{decision_key}", tags=["recommendations"]
    )
    def decision_get(decision_key: str) -> dict[str, Any]:
        """Fetch a single decision by its audit key."""
        with database.session() as session:
            try:
                return {"decision": get_decision(session, decision_key)}
            except DecisionError as exc:
                raise _http_error(exc) from exc

    @api.post("/api/v1/recommendations/decisions/release", tags=["recommendations"])
    def decision_release(req: ReleaseRequest) -> dict[str, Any]:
        """Free a committed unit back to ``available`` (EM-053 task completion)."""
        try:
            with database.session() as session:
                result = release_assignment(
                    session,
                    resource_key=req.resource_key,
                    event_key=req.event_key,
                    decided_by=req.decided_by,
                    reason=req.reason,
                )
                session.commit()
        except ConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": "conflict", "error": str(exc)},
            ) from exc
        except DecisionError as exc:
            raise _http_error(exc) from exc
        return {
            "status": "released" if result["released"] else "noop",
            **result,
            "attribution": _ASSIGN_ATTRIBUTION,
        }

    @api.get("/api/v1/recommendations/assignments", tags=["recommendations"])
    def assignments_list() -> dict[str, Any]:
        """List every unit currently booked to an incident (EM-053)."""
        with database.session() as session:
            rows = list_active_assignments(session)
        return {
            "count": len(rows),
            "assignments": rows,
            "attribution": _ASSIGN_ATTRIBUTION,
        }

    @api.post(
        "/api/v1/recommendations/assignments/release-completed",
        tags=["recommendations"],
    )
    def assignments_release_completed() -> dict[str, Any]:
        """Auto-free units whose incident is no longer active (EM-053)."""
        with database.session() as session:
            result = release_completed_assignments(session)
            session.commit()
        return {
            "status": "ok",
            **result,
            "attribution": _ASSIGN_ATTRIBUTION,
        }
