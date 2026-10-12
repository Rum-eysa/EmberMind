"""Rolling what-if run history endpoints (EM-062, Epic E6).

Auto-captures each what-if run into a short, self-trimming history so the
operator can scroll back through the last few attempts and revert to any one of
them. As with EM-059, only run *inputs* are stored; reverting replays them
through the existing what-if endpoint so nothing here duplicates the physics.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.whatif_history import (
    HistoryError,
    clear_history,
    get_history,
    list_history,
    record_history,
)

_HISTORY_ATTRIBUTION = "Ne denediğinin yuvarlanan geçmişi + tek tık geri alma: EM-062"


class HistoryRecordRequest(BaseModel):
    """Capture one what-if run (its inputs) into the rolling history."""

    model_config = {"protected_namespaces": ()}

    params: dict[str, Any]
    kind: str = "wind"
    event_key: str | None = None
    label: str | None = None


def register_whatif_history_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-062 what-if history endpoints."""

    enabled = bool(getattr(settings, "WHATIF_HISTORY_ENABLED", True))
    limit = int(getattr(settings, "WHATIF_HISTORY_LIMIT", 10))

    @api.get("/api/v1/whatif/history/config", tags=["history"])
    def history_config() -> dict[str, Any]:
        """Feature descriptor for the run-history panel."""
        return {
            "history": "whatif",
            "enabled": enabled,
            "limit": limit,
            "persistence": "inputs only (results replayed live)",
            "attribution": _HISTORY_ATTRIBUTION,
        }

    @api.post("/api/v1/whatif/history", tags=["history"])
    def history_record(req: HistoryRecordRequest) -> dict[str, Any]:
        """Record a what-if run; an exact repeat of the newest is skipped."""
        with database.session() as session:
            result = record_history(
                session,
                enabled=enabled,
                limit=limit,
                params=req.params,
                kind=req.kind,
                event_key=req.event_key,
                label=req.label,
            )
            session.commit()
        return {"status": "recorded", **result, "attribution": _HISTORY_ATTRIBUTION}

    @api.get("/api/v1/whatif/history", tags=["history"])
    def history_list(
        event_key: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        limit_n: int = Query(default=10, ge=1, le=50, alias="limit"),
    ) -> dict[str, Any]:
        """List recent runs, newest first, optionally filtered."""
        with database.session() as session:
            rows = list_history(
                session, event_key=event_key, kind=kind, limit=min(limit_n, limit)
            )
        return {
            "count": len(rows),
            "history": rows,
            "attribution": _HISTORY_ATTRIBUTION,
        }

    @api.delete("/api/v1/whatif/history", tags=["history"])
    def history_clear(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Clear the history (all runs, or one event's runs)."""
        with database.session() as session:
            removed = clear_history(session, event_key=event_key)
            session.commit()
        return {"status": "cleared", "removed": removed}

    @api.get("/api/v1/whatif/history/{history_id}", tags=["history"])
    def history_get(history_id: int) -> dict[str, Any]:
        """Fetch one run for a one-click revert."""
        with database.session() as session:
            try:
                return {"entry": get_history(session, history_id)}
            except HistoryError as exc:
                raise HTTPException(
                    status_code=404,
                    detail={"status": "error", "error": str(exc)},
                ) from exc
