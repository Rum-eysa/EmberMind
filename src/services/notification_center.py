"""Notification centre and audible-alert preferences (EM-086, Epic E8).

EM-032 pushes a single ``alert`` onto the live change feed whenever an
incident's risk band escalates, and EM-090 streams it to the operator map. But
the raw feed is not a *notification centre*: the operator cannot tell which
alerts they have already handled, a critical warning scrolls away, and the
audible alarm is all-or-nothing. EM-086 acceptance closes exactly that:

* every alert is listed with a **read / unread** state;
* the audible alarm can be **toggled** and **tuned by level**;
* a **critical alert stays visible until acknowledged**.

The alert content itself lives in ``live_updates`` (EM-032/EM-090); this
service never duplicates it. It layers a small amount of mutable *handling*
state on top (:class:`NotificationState`, one row per touched alert) plus a
single operator-wide audible configuration
(:class:`NotificationSoundSetting`), and projects them together into the panel.

Everything is deterministic: alerts are ordered newest-first by their monotonic
feed id, unknown levels rank lowest, and a fresh alert defaults to
unread/unacknowledged until the operator acts on it.
"""
import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.live import LiveUpdate
from src.models.notification_center import (
    ACK_REQUIRED_LEVELS,
    SOUND_SETTING_KEY,
    NotificationSoundSetting,
    NotificationState,
)
from src.services.risk_index import RISK_LEVELS
from src.utils.timeutils import to_utc_iso, utc_now

# normal < dikkat < kritik-yakin < kritik; unknown bands rank lowest (0) so they
# never outrank a real escalation for the audible "at or above" test.
_LEVEL_RANK = {level: index for index, level in enumerate(RISK_LEVELS)}

DEFAULT_MAX_ALERTS = 100

NOTIFICATION_ATTRIBUTION = (
    "EM-086: bildirim merkezi - canlı akıştaki her uyarı okundu/okunmadı "
    "durumuyla listelenir, kritik uyarı onaylanana kadar görünür kalır ve "
    "sesli uyarı açılıp kapatılabilir / seviyeye göre ayarlanabilir"
)
NOTIFICATION_PERSISTENCE = "notification_states + notification_sound_settings"


class NotificationCenterError(Exception):
    """Raised for an unknown alert or an invalid audible setting."""


def _rank(level: Any) -> int:
    """Urgency rank of a risk band (unknown -> lowest)."""
    return _LEVEL_RANK.get(str(level).strip().lower(), 0)


def _max_alerts(settings: Any) -> int:
    try:
        want = int(getattr(settings, "NOTIFICATION_MAX_ALERTS", DEFAULT_MAX_ALERTS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ALERTS
    return max(1, want)


def _payload_of(row: LiveUpdate) -> dict[str, Any]:
    """Decode a live-feed row's JSON payload (empty dict when absent/bad)."""
    raw = row.payload_json
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _default_sound_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "NOTIFICATION_SOUND_ENABLED", True))


def _default_min_level(settings: Any) -> str:
    level = str(getattr(settings, "NOTIFICATION_SOUND_MIN_LEVEL", "dikkat"))
    return level if level in _LEVEL_RANK else "dikkat"


def _sound_row(session: Session) -> Optional[NotificationSoundSetting]:
    return session.scalars(
        select(NotificationSoundSetting)
        .where(NotificationSoundSetting.setting_key == SOUND_SETTING_KEY)
        .order_by(NotificationSoundSetting.id.desc())
    ).first()


def get_sound_setting(session: Session, settings: Any) -> dict[str, Any]:
    """Operator-wide audible config, seeded from settings on first read.

    A missing row is *not* written here - it simply reports the settings default
    with ``source`` ``settings_default`` so the panel is never empty. Only an
    explicit :func:`update_sound_setting` persists a row.
    """
    row = _sound_row(session)
    if row is None:
        return {
            "setting_key": SOUND_SETTING_KEY,
            "sound_enabled": _default_sound_enabled(settings),
            "min_level": _default_min_level(settings),
            "source": "settings_default",
            "levels": list(RISK_LEVELS),
        }
    payload = dict(row.as_dict)
    payload["source"] = "stored"
    payload["levels"] = list(RISK_LEVELS)
    return payload


def should_sound(level: Any, sound: dict[str, Any]) -> bool:
    """Whether an alert at ``level`` triggers the audible alarm under ``sound``."""
    if not bool(sound.get("sound_enabled")):
        return False
    return _rank(level) >= _rank(sound.get("min_level"))


def update_sound_setting(
    session: Session,
    settings: Any,
    *,
    sound_enabled: Optional[bool] = None,
    min_level: Optional[str] = None,
) -> dict[str, Any]:
    """Toggle the audible alarm and/or raise its minimum sounding level."""
    if min_level is not None and min_level not in _LEVEL_RANK:
        raise NotificationCenterError(f"bilinmeyen risk seviyesi: {min_level}")
    row = _sound_row(session)
    if row is None:
        row = NotificationSoundSetting(
            setting_key=SOUND_SETTING_KEY,
            sound_enabled=_default_sound_enabled(settings),
            min_level=_default_min_level(settings),
        )
        session.add(row)
        session.flush()
    if sound_enabled is not None:
        row.sound_enabled = bool(sound_enabled)  # type: ignore[assignment]
    if min_level is not None:
        row.min_level = str(min_level)  # type: ignore[assignment]
    session.flush()
    return get_sound_setting(session, settings)


def _alert_rows(session: Session, limit: int) -> list[LiveUpdate]:
    """The most recent ``alert`` entries on the live feed, newest first."""
    rows = session.scalars(
        select(LiveUpdate)
        .where(LiveUpdate.kind == "alert")
        .order_by(LiveUpdate.id.desc())
        .limit(limit)
    ).all()
    return list(rows)


def _state_map(session: Session, ids: list[int]) -> dict[int, NotificationState]:
    """Existing handling rows keyed by the alert they track."""
    if not ids:
        return {}
    rows = session.scalars(
        select(NotificationState).where(NotificationState.live_update_id.in_(ids))
    ).all()
    return {int(row.live_update_id): row for row in rows}


def list_notifications(
    session: Session,
    settings: Any,
    *,
    only_active: bool = False,
) -> dict[str, Any]:
    """Project every live-feed alert with its read / acknowledge state.

    ``only_active`` trims the returned list to alerts still pinning the panel
    (a critical one until acknowledged, anything else until read); the summary
    counts always describe the whole window so the badge never lies.
    """
    limit = _max_alerts(settings)
    rows = _alert_rows(session, limit)
    states = _state_map(session, [int(row.id) for row in rows])
    sound = get_sound_setting(session, settings)

    items: list[dict[str, Any]] = []
    unread = pending_ack = sounding = 0
    for row in rows:
        payload = _payload_of(row)
        level = str(payload.get("to_level") or "")
        state = states.get(int(row.id))
        is_read = bool(state.is_read) if state is not None else False
        is_ack = bool(state.is_acknowledged) if state is not None else False
        requires_ack = level in ACK_REQUIRED_LEVELS
        still_showing = (not is_ack) if requires_ack else (not is_read)
        audible = should_sound(level, sound) and still_showing
        if not is_read:
            unread += 1
        if requires_ack and not is_ack:
            pending_ack += 1
        if audible:
            sounding += 1
        items.append(
            {
                "live_update_id": int(row.id),
                "event_key": row.event_key,
                "title": row.title,
                "message": row.message,
                "source": row.source,
                "level": level,
                "level_rank": _rank(level),
                "from_level": payload.get("from_level"),
                "requires_ack": requires_ack,
                "is_read": is_read,
                "is_acknowledged": is_ack,
                "still_showing": still_showing,
                "would_sound": audible,
                "read_at": to_utc_iso(state.read_at)
                if state is not None and state.read_at
                else None,
                "acknowledged_at": to_utc_iso(state.acknowledged_at)
                if state is not None and state.acknowledged_at
                else None,
                "created_at": to_utc_iso(row.created_at),
            }
        )

    shown = [item for item in items if item["still_showing"]] if only_active else items
    return {
        "panel": "notification_center",
        "generated_at": to_utc_iso(utc_now()),
        "notifications": shown,
        "returned_count": len(shown),
        "levels": list(RISK_LEVELS),
        "ack_required_levels": list(ACK_REQUIRED_LEVELS),
        "sound": sound,
        "summary": {
            "total": len(items),
            "unread": unread,
            "pending_ack": pending_ack,
            "sounding": sounding,
            "still_showing": sum(1 for item in items if item["still_showing"]),
        },
        "max_alerts": limit,
        "attribution": NOTIFICATION_ATTRIBUTION,
        "persistence": NOTIFICATION_PERSISTENCE,
    }


def _get_alert(session: Session, live_update_id: int) -> LiveUpdate:
    row = session.get(LiveUpdate, int(live_update_id))
    if row is None or str(row.kind) != "alert":
        raise NotificationCenterError(f"uyarı bulunamadı: {live_update_id}")
    return row


def _touch_state(
    session: Session, live_update_id: int
) -> tuple[LiveUpdate, NotificationState]:
    row = _get_alert(session, live_update_id)
    state = session.scalars(
        select(NotificationState).where(NotificationState.live_update_id == int(row.id))
    ).first()
    if state is None:
        state = NotificationState(live_update_id=int(row.id))
        session.add(state)
        session.flush()
    return row, state


def mark_read(session: Session, live_update_id: int) -> dict[str, Any]:
    """Flag one alert as read (does not clear an ack-required critical)."""
    _, state = _touch_state(session, live_update_id)
    if not bool(state.is_read):
        state.is_read = True  # type: ignore[assignment]
        state.read_at = utc_now()  # type: ignore[assignment]
        session.flush()
    return dict(state.as_dict)


def acknowledge(session: Session, live_update_id: int) -> dict[str, Any]:
    """Acknowledge one alert - the only action that clears a critical pin.

    Acknowledging also implies the alert was read, so the read flag is set too.
    """
    _, state = _touch_state(session, live_update_id)
    now = utc_now()
    if not bool(state.is_read):
        state.is_read = True  # type: ignore[assignment]
        state.read_at = now  # type: ignore[assignment]
    if not bool(state.is_acknowledged):
        state.is_acknowledged = True  # type: ignore[assignment]
        state.acknowledged_at = now  # type: ignore[assignment]
    session.flush()
    return dict(state.as_dict)


def mark_all_read(session: Session, settings: Any) -> dict[str, Any]:
    """Read every alert in the current window (critical ones still pin until ack)."""
    rows = _alert_rows(session, _max_alerts(settings))
    existing = _state_map(session, [int(row.id) for row in rows])
    updated = 0
    for row in rows:
        rid = int(row.id)
        state = existing.get(rid)
        if state is None:
            state = NotificationState(live_update_id=rid)
            session.add(state)
        if not bool(state.is_read):
            state.is_read = True  # type: ignore[assignment]
            state.read_at = utc_now()  # type: ignore[assignment]
            updated += 1
    session.flush()
    return {"marked_read": updated, "window": len(rows)}


def notification_center_config(settings: Any) -> dict[str, Any]:
    """Descriptive payload: level ladder, ack-required bands, defaults, bounds."""
    return {
        "levels": [
            {"code": level, "rank": _LEVEL_RANK[level]} for level in RISK_LEVELS
        ],
        "ack_required_levels": list(ACK_REQUIRED_LEVELS),
        "default_sound": {
            "sound_enabled": _default_sound_enabled(settings),
            "min_level": _default_min_level(settings),
        },
        "max_alerts": _max_alerts(settings),
        "sources": [
            "live_updates (kind=alert, EM-032/EM-090)",
            "notification_states (read/ack, EM-086)",
            "notification_sound_settings (audible, EM-086)",
        ],
        "attribution": NOTIFICATION_ATTRIBUTION,
        "persistence": NOTIFICATION_PERSISTENCE,
    }


__all__ = [
    "ACK_REQUIRED_LEVELS",
    "DEFAULT_MAX_ALERTS",
    "NOTIFICATION_ATTRIBUTION",
    "NOTIFICATION_PERSISTENCE",
    "NotificationCenterError",
    "acknowledge",
    "get_sound_setting",
    "list_notifications",
    "mark_all_read",
    "mark_read",
    "notification_center_config",
    "should_sound",
    "update_sound_setting",
]
