"""Joint cross-border early-warning notification endpoints (EM-069, Epic E7).

Turns the EM-067 border-crossing projection into the coordinated action: warn
the partner country's coordination unit over a pre-defined channel when a fire
is projected to cross the border within the agreed likelihood and lead time. A
read-only status shows which crossings warrant a warning and whether one has
already been dispatched; a sweep creates (edge-triggered) and auto-resolves the
open warnings; the log lists every dispatch. Errors map to 400.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.crossborder_notification import (
    COORDINATION_CHANNELS,
    NOTIF_ATTRIBUTION,
    NOTIF_PERSISTENCE,
    NotificationError,
    dispatch,
    list_notifications,
    notification_status,
    sweep,
)


def register_crossborder_notification_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-069 early-warning notification feeds."""

    @api.get("/api/v1/crossborder/notifications/config", tags=["panel"])
    def notification_config() -> dict[str, Any]:
        """Descriptor: thresholds, lifecycle and the pre-defined channels."""
        return {
            "min_likelihood": float(
                getattr(settings, "CROSSBORDER_NOTIFY_MIN_LIKELIHOOD", 0.4)
            ),
            "notify_window_minutes": int(
                getattr(settings, "CROSSBORDER_NOTIFY_WINDOW_MINUTES", 120)
            ),
            "enabled": bool(getattr(settings, "CROSSBORDER_NOTIFY_ENABLED", True)),
            "edge_triggered": True,
            "statuses": ["open", "resolved"],
            "channels": dict(COORDINATION_CHANNELS),
            "attribution": NOTIF_ATTRIBUTION,
            "persistence": NOTIF_PERSISTENCE,
        }

    @api.get("/api/v1/crossborder/notifications", tags=["panel"])
    def notification_list(
        event_key: str | None = Query(default=None),
        target: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit_n: int = Query(default=50, ge=1, le=200, alias="limit"),
    ) -> dict[str, Any]:
        """Dispatched early-warning log (newest first), optionally filtered."""
        with database.session() as session:
            rows = list_notifications(
                session,
                event_key=event_key,
                target=target,
                status=status,
                limit=limit_n,
            )
        return {
            "count": len(rows),
            "notifications": rows,
            "attribution": NOTIF_ATTRIBUTION,
            "persistence": NOTIF_PERSISTENCE,
        }

    @api.get("/api/v1/crossborder/notification-status", tags=["panel"])
    def notification_status_view() -> dict[str, Any]:
        """Which crossings pass the threshold and whether each was notified."""
        with database.session() as session:
            return notification_status(session, settings)

    @api.post("/api/v1/crossborder/notifications/sweep", tags=["panel"])
    def notification_sweep() -> dict[str, Any]:
        """Edge-triggered dispatch + auto-resolve across active crossings."""
        with database.session() as session:
            result = sweep(session, settings)
            session.commit()
        return {
            "status": "ok",
            "attribution": NOTIF_ATTRIBUTION,
            "persistence": NOTIF_PERSISTENCE,
            **result,
        }

    @api.post("/api/v1/crossborder/notifications", tags=["panel"])
    def notification_dispatch(
        event_key: str = Query(...),
        target_country: str = Query(...),
    ) -> dict[str, Any]:
        """Dispatch (or reuse) one early warning to the partner for an event."""
        try:
            with database.session() as session:
                result = dispatch(session, settings, event_key, target_country)
                session.commit()
        except NotificationError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        return {
            "status": "created" if result["created"] else "existing",
            "deduped": result["deduped"],
            "attribution": NOTIF_ATTRIBUTION,
            "notification": result["notification"],
        }
