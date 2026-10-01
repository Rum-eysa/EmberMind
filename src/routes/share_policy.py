"""Country / role data-sharing policy endpoints (EM-070, Epic E7).

An administrator sets which field groups (``fire`` / ``risk`` / ``support``) an
owner country exposes to the partner across the shared screen, per role scope.
A ``preview`` shows exactly what would be visible before applying it, and every
change is stored append-only so the effective policy and its audit trail share
one table. This is the durable *authorization* layer EM-066 deferred.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.crossborder_situation import SHAREABLE_FIELD_GROUPS
from src.services.share_policy import (
    DEFAULT_ROLE,
    SHARE_POLICY_ATTRIBUTION,
    SharePolicyError,
    audit_trail,
    policy_matrix,
    preview_sharing,
    set_policy,
)


class SharePolicyRequest(BaseModel):
    """One administrator policy change for a country and role scope."""

    country: str
    role: str | None = None
    shared_fields: list[str]
    changed_by: str | None = None
    reason: str | None = None


def register_share_policy_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-070 data-sharing policy feeds."""

    @api.get("/api/v1/share-policy", tags=["panel"])
    def share_policy_matrix() -> dict[str, Any]:
        """Every country's default and named-role effective policies."""
        with database.session() as session:
            return policy_matrix(session, settings)

    @api.get("/api/v1/share-policy/preview", tags=["panel"])
    def share_policy_preview(
        country: str = Query(default="TR"),
        role: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Exactly what the partner would see for this country / role (no write)."""
        try:
            with database.session() as session:
                preview = preview_sharing(
                    session, settings, country, role or DEFAULT_ROLE
                )
        except SharePolicyError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        return {**preview, "attribution": SHARE_POLICY_ATTRIBUTION}

    @api.post("/api/v1/share-policy", tags=["panel"])
    def share_policy_set(req: SharePolicyRequest) -> dict[str, Any]:
        """Set the shared field groups for a country / role (appends audit)."""
        try:
            with database.session() as session:
                result = set_policy(
                    session,
                    settings,
                    req.country,
                    req.role or DEFAULT_ROLE,
                    req.shared_fields,
                    changed_by=req.changed_by,
                    reason=req.reason,
                )
                session.commit()
        except SharePolicyError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        return {
            "status": "set",
            "attribution": SHARE_POLICY_ATTRIBUTION,
            "field_groups": list(SHAREABLE_FIELD_GROUPS),
            **result,
        }

    @api.get("/api/v1/share-policy/audit", tags=["panel"])
    def share_policy_audit(
        country: str | None = Query(default=None),
        role: str | None = Query(default=None),
        limit_n: int = Query(default=50, ge=1, le=200, alias="limit"),
    ) -> dict[str, Any]:
        """Policy change history (newest first), optionally filtered."""
        try:
            with database.session() as session:
                rows = audit_trail(session, country=country, role=role, limit=limit_n)
        except SharePolicyError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        return {
            "count": len(rows),
            "changes": rows,
            "attribution": SHARE_POLICY_ATTRIBUTION,
            "persistence": "country_share_policy",
        }
