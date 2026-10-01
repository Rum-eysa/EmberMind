"""Notification-center state and audible-alert preferences (EM-086, Epic E8).

EM-032 already pushes a single ``alert`` onto the live change feed whenever an
incident's risk band escalates, and EM-090 streams it to the operator map. But
the raw feed is not a *notification centre*: the operator cannot see which
alerts they have already handled, a critical warning scrolls away, and the
audible alarm is all-or-nothing (EM-086 acceptance: "every alert is listed with
a read/unread state; the audible alarm can be toggled and tuned by level; a
critical alert stays until acknowledged").

Two small persisted surfaces close that gap:

* :class:`NotificationState` - one mutable row per live-feed ``alert`` (keyed by
  ``live_update_id``) carrying the read and acknowledge state. The alert content
  itself stays in ``live_updates``; this table only tracks what the operator has
  done with it, so a fresh alert needs no write here until it is touched.
* :class:`NotificationSoundSetting` - a single operator-wide row for the audible
  alarm: on/off plus the minimum risk band that should sound. It defaults from
  settings on first read so the behaviour is never empty.

Both tables are purely additive.
"""
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# Risk bands that must be *acknowledged* (not merely read) before they stop
# pinning to the notification centre (EM-086: "critical alert stays visible
# until acknowledged"). Read alone does not clear these.
ACK_REQUIRED_LEVELS = ("kritik-yakin", "kritik")

# The one operator-wide audible-config row uses this fixed key.
SOUND_SETTING_KEY = "default"


class NotificationState(BaseModel):
    """Read / acknowledge state for one live-feed ``alert`` row."""

    __tablename__ = "notification_states"

    # Unique so an alert is tracked at most once; indexed for the join.
    live_update_id = Column(Integer, unique=True, nullable=False, index=True)
    is_read = Column(Boolean, nullable=False, default=False)
    is_acknowledged = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """API-friendly view of one alert's handling state."""
        return {
            "id": self.id,
            "live_update_id": self.live_update_id,
            "is_read": bool(self.is_read),
            "is_acknowledged": bool(self.is_acknowledged),
            "read_at": to_utc_iso(self.read_at) if self.read_at else None,
            "acknowledged_at": (
                to_utc_iso(self.acknowledged_at) if self.acknowledged_at else None
            ),
            "updated_at": to_utc_iso(self.updated_at),
        }


class NotificationSoundSetting(BaseModel):
    """Operator-wide audible-alert configuration (a single row)."""

    __tablename__ = "notification_sound_settings"

    setting_key = Column(
        String(32), unique=True, nullable=False, default=SOUND_SETTING_KEY, index=True
    )
    sound_enabled = Column(Boolean, nullable=False, default=True)
    # Minimum risk band that triggers the audible alarm (at or above this).
    min_level = Column(String(32), nullable=False, default="dikkat")

    @property
    def as_dict(self) -> dict[str, Any]:
        """API-friendly view of the audible-alarm configuration."""
        return {
            "id": self.id,
            "setting_key": self.setting_key,
            "sound_enabled": bool(self.sound_enabled),
            "min_level": self.min_level,
            "updated_at": to_utc_iso(self.updated_at),
        }
