"""Unified audit trail endpoints (EM-096, Epic E10).

Exposes the cross-domain accountability ledger: append an immutable entry,
read the trail back newest-first with filters, and a panel feed combining the
recent entries with a per-domain count. Deliberately **no** update or delete
routes - the ledger cannot be altered after the fact.
"""
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.audit_trail import (
    AuditError,
    audit_config,
    count_by_domain,
    list_audit,
    record_audit,
)


class AuditRecordRequest(BaseModel):
    """Payload for appending one immutable audit entry."""

    domain: str
    action: str
    actor: str
    subject_key: Optional[str] = None
    summary: Optional[str] = None
    old_value: Any = None
    new_value: Any = None


def _http_error(exc: AuditError) -> HTTPException:
    """Map a service error to 400 (an invalid ledger write)."""
    return HTTPException(status_code=400, detail={"status": "error", "error": str(exc)})


def register_audit_trail_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-096 unified audit-trail endpoints."""

    @api.get("/api/v1/audit/config", tags=["audit"])
    def audit_config_endpoint() -> dict[str, Any]:
        """Controlled vocabularies (domains/actions) and the immutability policy."""
        return audit_config(settings)

    @api.get("/api/v1/audit", tags=["audit"])
    def audit_overview(
        domain: Optional[str] = Query(default=None),
        actor: Optional[str] = Query(default=None),
        subject_key: Optional[str] = Query(default=None),
        limit: Optional[int] = Query(default=None, ge=1, le=500),
    ) -> dict[str, Any]:
        """Panel feed: recent immutable entries plus a per-domain tally."""
        with database.session() as session:
            listing = list_audit(
                session,
                settings,
                domain=domain,
                actor=actor,
                subject_key=subject_key,
                limit=limit,
            )
            return {**listing, "counts_by_domain": count_by_domain(session)}

    @api.post("/api/v1/audit", tags=["audit"])
    def audit_record(req: AuditRecordRequest) -> dict[str, Any]:
        """Append one immutable accountability entry (kim/ne zaman/ne değişim)."""
        detail = {
            "subject_key": req.subject_key,
            "summary": req.summary,
            "old_value": req.old_value,
            "new_value": req.new_value,
        }
        try:
            with database.session() as session:
                entry = record_audit(
                    session, settings, req.domain, req.action, req.actor, detail
                )
                session.commit()
        except AuditError as exc:
            raise _http_error(exc) from exc
        return {"status": "recorded", "entry": entry}
