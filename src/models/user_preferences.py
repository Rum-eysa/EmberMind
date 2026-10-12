"""Persisted operator preference profile (EM-088, Epic E8).

The interface language (EM-068) and the display standardisation knobs
(EM-063 - time zone, coordinate format) are both *stateless*: the chosen
language lives only in the browser's ``localStorage`` and the display helper
re-derives everything from the request each time, so neither reports a
persisted preference (both advertise ``persistence == "none"``). The theme
toggle likewise never leaves the local machine. That means an operator who
switches workstation, or a second crew member opening the same panel, loses
their language / unit / theme choices.

EM-088 closes exactly that gap with one small operator-wide row: a saved
profile carrying the four display knobs the system already honours, so the
choice survives a reload / different machine and can be reset to the settings
default with a single action. Like :class:`NotificationSoundSetting`
(EM-086), it uses a fixed key so there is at most one row, and the service
seeds it from settings on first read so the panel is never empty.

The table is purely additive.
"""
from typing import Any

from sqlalchemy import Column, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# The one operator-wide profile row uses this fixed key (mirrors EM-086 sound).
PREFERENCE_KEY = "default"

# Interface themes the operator map / panel expose (EM-075 binary toggle).
THEMES = ("dark", "light")
DEFAULT_THEME = "dark"


class UserPreference(BaseModel):
    """Operator-wide saved display profile (a single row)."""

    __tablename__ = "user_preferences"

    preference_key = Column(
        String(32), unique=True, nullable=False, default=PREFERENCE_KEY, index=True
    )
    # Interface language code (validated against the EM-068 catalogue).
    language = Column(String(8), nullable=False, default="tr")
    # Interface theme (validated against :data:`THEMES`).
    theme = Column(String(16), nullable=False, default=DEFAULT_THEME)
    # Displayed time zone, an IANA name (validated against EM-063 zones).
    timezone = Column(String(64), nullable=False, default="Europe/Istanbul")
    # Coordinate display format (validated against EM-063 formats).
    coordinate_format = Column(String(16), nullable=False, default="decimal")

    @property
    def as_dict(self) -> dict[str, Any]:
        """API-friendly view of the saved operator profile."""
        return {
            "id": self.id,
            "preference_key": self.preference_key,
            "language": self.language,
            "theme": self.theme,
            "timezone": self.timezone,
            "coordinate_format": self.coordinate_format,
            "updated_at": to_utc_iso(self.updated_at),
        }
