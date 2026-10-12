"""Notification centre and audible-alert endpoints (EM-086, Epic E8).

Lists every live-feed alert with its read / acknowledge state, lets the operator
mark alerts read or acknowledge a critical one (the only action that clears its
pin), and reads / updates the operator-wide audible-alarm configuration.
"""
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.notification_center import (
    NotificationCenterError,
    acknowledge,
    get_sound_setting,
    list_notifications,
    mark_all_read,
    mark_read,
    notification_center_config,
    update_sound_setting,
)


class SoundRequest(BaseModel):
    """Toggle the audible alarm and/or raise its minimum sounding level."""

    sound_enabled: Optional[bool] = None
    min_level: Optional[str] = None


def _http_error(exc: NotificationCenterError) -> HTTPException:
    """Map a service error to the right HTTP status (missing vs invalid)."""
    text = str(exc)
    status = 404 if ("bulunamadı" in text or "not found" in text) else 400
    return HTTPException(status_code=status, detail={"status": "error", "error": text})


def register_notification_center_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-086 notification-centre endpoints."""

    @api.get("/api/v1/notifications/config", tags=["panel"])
    def notifications_config() -> dict[str, Any]:
        """Level ladder, ack-required bands, audible defaults and bounds."""
        return notification_center_config(settings)

    @api.get("/api/v1/notifications", tags=["panel"])
    def notifications_list(
        only_active: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Every alert with read / acknowledge state and the audible config."""
        with database.session() as session:
            return list_notifications(session, settings, only_active=only_active)

    @api.get("/api/v1/notifications/sound", tags=["panel"])
    def notifications_sound_get() -> dict[str, Any]:
        """The current audible-alarm configuration."""
        with database.session() as session:
            return get_sound_setting(session, settings)

    @api.put("/api/v1/notifications/sound", tags=["panel"])
    def notifications_sound_put(req: SoundRequest) -> dict[str, Any]:
        """Toggle the audible alarm and/or tune its minimum level."""
        try:
            with database.session() as session:
                result = update_sound_setting(
                    session,
                    settings,
                    sound_enabled=req.sound_enabled,
                    min_level=req.min_level,
                )
                session.commit()
        except NotificationCenterError as exc:
            raise _http_error(exc) from exc
        return result

    @api.post("/api/v1/notifications/read-all", tags=["panel"])
    def notifications_read_all() -> dict[str, Any]:
        """Mark every alert in the window read (critical ones still pin)."""
        with database.session() as session:
            result = mark_all_read(session, settings)
            session.commit()
        return {"status": "ok", **result}

    @api.post("/api/v1/notifications/{live_update_id}/read", tags=["panel"])
    def notifications_mark_read(live_update_id: int) -> dict[str, Any]:
        """Flag a single alert as read."""
        try:
            with database.session() as session:
                result = mark_read(session, live_update_id)
                session.commit()
        except NotificationCenterError as exc:
            raise _http_error(exc) from exc
        return {"status": "read", **result}

    @api.post("/api/v1/notifications/{live_update_id}/acknowledge", tags=["panel"])
    def notifications_acknowledge(live_update_id: int) -> dict[str, Any]:
        """Acknowledge a single alert - clears a critical pin."""
        try:
            with database.session() as session:
                result = acknowledge(session, live_update_id)
                session.commit()
        except NotificationCenterError as exc:
            raise _http_error(exc) from exc
        return {"status": "acknowledged", **result}
