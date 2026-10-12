"""Operator verification endpoints for silent-region alerts (EM-041, Epic E4).

Lets the operator mark an EM-040 silent-region alert as **verified** /
**false alarm** / **under review**. Each marking appends an audit row (the
previous verdict is kept), so the current state can be read back and the
recorded feedback turned into a model-improvement signal.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.models.silent_zone_verification import VERIFICATION_STATUSES
from src.services.silent_zone_verification import (
    SILENT_ZONE_VERIFICATION_ATTRIBUTION,
    SILENT_ZONE_VERIFICATION_PERSISTENCE,
    SilentZoneVerificationError,
    current_verdicts,
    feedback_summary,
    get_current_verification,
    list_verifications,
    record_verification,
    verification_config,
)


class VerificationRequest(BaseModel):
    """One operator verdict on a silent-region alert."""

    model_config = {"protected_namespaces": ()}

    region_id: int
    status: str
    region_name: str | None = None
    reason: str | None = None
    verified_by: str | None = None
    detail: dict[str, Any] | None = None


def _http_error(exc: SilentZoneVerificationError) -> HTTPException:
    """Map a service error to the right HTTP status (missing vs invalid)."""
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(
        status_code=status, detail={"status": "error", "error": str(exc)}
    )


def register_silent_zone_verification_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-041 silent-zone verification workflow."""

    @api.get("/api/v1/silent-zone-verifications/config", tags=["panel"])
    def silent_zone_verification_config() -> dict[str, Any]:
        """Verdict catalogue, the append-only rule and the feedback signal."""
        return verification_config(settings)

    @api.post("/api/v1/silent-zone-verifications", tags=["panel"])
    def silent_zone_verification_record(req: VerificationRequest) -> dict[str, Any]:
        """Append one operator verdict on a silent-region alert."""
        try:
            with database.session() as session:
                result = record_verification(
                    session,
                    region_id=req.region_id,
                    status=req.status,
                    region_name=req.region_name,
                    reason=req.reason,
                    verified_by=req.verified_by,
                    detail=req.detail,
                )
                session.commit()
        except SilentZoneVerificationError as exc:
            raise _http_error(exc) from exc
        return {
            "status": "recorded",
            **result,
            "attribution": SILENT_ZONE_VERIFICATION_ATTRIBUTION,
            "persistence": SILENT_ZONE_VERIFICATION_PERSISTENCE,
        }

    @api.get("/api/v1/silent-zone-verifications", tags=["panel"])
    def silent_zone_verification_list(
        status: str | None = Query(default=None),
        region_id: int | None = Query(default=None),
        limit_n: int = Query(default=50, ge=1, le=200, alias="limit"),
    ) -> dict[str, Any]:
        """List recorded verdicts (newest first), optionally filtered."""
        try:
            with database.session() as session:
                rows = list_verifications(
                    session, status=status, region_id=region_id, limit=limit_n
                )
        except SilentZoneVerificationError as exc:
            raise _http_error(exc) from exc
        return {
            "count": len(rows),
            "statuses": list(VERIFICATION_STATUSES),
            "verifications": rows,
            "attribution": SILENT_ZONE_VERIFICATION_ATTRIBUTION,
            "persistence": SILENT_ZONE_VERIFICATION_PERSISTENCE,
        }

    @api.get("/api/v1/silent-zone-verifications/current", tags=["panel"])
    def silent_zone_verification_current(
        region_id: int | None = Query(default=None),
    ) -> dict[str, Any]:
        """Current verdict per region: one region's newest, or every region's."""
        with database.session() as session:
            if region_id is not None:
                return {
                    "region_id": region_id,
                    "verification": get_current_verification(session, region_id),
                }
            verdicts = current_verdicts(session)
        rows = sorted(verdicts.values(), key=lambda v: str(v["region_name"]))
        return {
            "count": len(rows),
            "verdicts": rows,
            "attribution": SILENT_ZONE_VERIFICATION_ATTRIBUTION,
        }

    @api.get("/api/v1/silent-zone-verifications/feedback", tags=["panel"])
    def silent_zone_verification_feedback() -> dict[str, Any]:
        """Model-improvement signal: per-status counts + false-alarm rate."""
        with database.session() as session:
            summary = feedback_summary(session)
        return {
            **summary,
            "attribution": SILENT_ZONE_VERIFICATION_ATTRIBUTION,
            "persistence": SILENT_ZONE_VERIFICATION_PERSISTENCE,
        }
