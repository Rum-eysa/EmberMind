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
    DecisionError,
    get_decision,
    list_decisions,
    record_decision,
)

_DECISION_ATTRIBUTION = "Öneri üzerinde operatör kararı (kabul/ret/düzenleme): EM-047"


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
