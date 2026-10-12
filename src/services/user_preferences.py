"""Persisted operator preference profile (EM-088, Epic E8).

An operator should be able to pick an interface **language**, a **theme** and a
**unit / display** convention and have that choice survive a page reload or a
different workstation. Until now those knobs were never saved: EM-068 keeps the
chosen language only in the browser's ``localStorage`` (``persistence == none``)
and EM-063 re-derives time zone / coordinate format from each request
(``persistence == none``), while the theme toggle never leaves the local
machine. This service turns those ephemeral knobs into one small saved profile,
so EM-088 acceptance holds:

* the settings are **stored under a profile** (a single operator-wide row);
* a change is **applied immediately** (the write returns the fresh profile the
  UI re-renders from);
* there is a **reset to default** (drop back to the settings-derived defaults).

Everything is deterministic and validated against the value sets the rest of the
system already honours: the language against the EM-068 catalogue, the time
zone / coordinate format against EM-063, and the theme against the two
interface themes. A missing profile is *not* written on read - it simply
reports the settings defaults with ``source == "settings_default"`` so the panel
is never empty; only an explicit :func:`update_preferences` persists a row.
"""
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.user_preferences import (
    DEFAULT_THEME,
    PREFERENCE_KEY,
    THEMES,
    UserPreference,
)
from src.services.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from src.services.localization import (
    COORDINATE_FORMATS,
    DEFAULT_COORDINATE_FORMAT,
    DEFAULT_TIMEZONE,
    SUPPORTED_TIMEZONES,
)
from src.utils.timeutils import to_utc_iso, utc_now

PREFERENCE_ATTRIBUTION = (
    "EM-088: kullanıcı ayarları (dil, tema, saat dilimi, koordinat biçimi) "
    "tek bir operatör profili satırında saklanır; varsayılana tek tıkla dönülür"
)
PREFERENCE_PERSISTENCE = "user_preferences"


class UserPreferenceError(Exception):
    """Raised when a submitted preference value is not in the allowed set."""


def _default_language(settings: Any) -> str:
    lang = str(getattr(settings, "I18N_DEFAULT_LANGUAGE", DEFAULT_LANGUAGE))
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def _default_theme(settings: Any) -> str:
    theme = str(getattr(settings, "UI_DEFAULT_THEME", DEFAULT_THEME))
    return theme if theme in THEMES else DEFAULT_THEME


def _default_timezone(settings: Any) -> str:
    tz = str(getattr(settings, "DISPLAY_TIMEZONE", DEFAULT_TIMEZONE))
    return tz if tz in SUPPORTED_TIMEZONES else DEFAULT_TIMEZONE


def _default_coordinate_format(settings: Any) -> str:
    fmt = str(getattr(settings, "DISPLAY_COORDINATE_FORMAT", DEFAULT_COORDINATE_FORMAT))
    return fmt if fmt in COORDINATE_FORMATS else DEFAULT_COORDINATE_FORMAT


def settings_defaults(settings: Any) -> dict[str, str]:
    """The four display knobs derived from configuration."""
    return {
        "language": _default_language(settings),
        "theme": _default_theme(settings),
        "timezone": _default_timezone(settings),
        "coordinate_format": _default_coordinate_format(settings),
    }


def _pref_row(session: Session) -> Optional[UserPreference]:
    return session.scalars(
        select(UserPreference)
        .where(UserPreference.preference_key == PREFERENCE_KEY)
        .order_by(UserPreference.id.desc())
    ).first()


def get_preferences(session: Session, settings: Any) -> dict[str, Any]:
    """The saved operator profile, seeded from settings on first read.

    A missing row reports the settings defaults (``source == settings_default``)
    without persisting anything, so the panel is never empty on a fresh install.
    """
    row = _pref_row(session)
    if row is None:
        payload: dict[str, Any] = dict(settings_defaults(settings))
        payload["preference_key"] = PREFERENCE_KEY
        payload["source"] = "settings_default"
        payload["updated_at"] = None
        return payload
    stored: dict[str, Any] = dict(row.as_dict)
    stored["source"] = "stored"
    return stored


def _validate(field: str, value: str, allowed: tuple[str, ...]) -> str:
    text = str(value).strip()
    if text not in allowed:
        raise UserPreferenceError(
            f"gecersiz {field}: {value} (izin verilenler: {', '.join(allowed)})"
        )
    return text


def update_preferences(
    session: Session,
    settings: Any,
    *,
    language: Optional[str] = None,
    theme: Optional[str] = None,
    timezone: Optional[str] = None,
    coordinate_format: Optional[str] = None,
) -> dict[str, Any]:
    """Validate and persist any subset of the operator profile.

    Each supplied field is checked against the value set the system already
    honours; unsupplied fields keep their current (or settings-default) value.
    The first write materialises the single profile row from the defaults.
    """
    if language is not None:
        language = _validate("dil", language, SUPPORTED_LANGUAGES)
    if theme is not None:
        theme = _validate("tema", theme, THEMES)
    if timezone is not None:
        timezone = _validate("saat dilimi", timezone, SUPPORTED_TIMEZONES)
    if coordinate_format is not None:
        coordinate_format = _validate(
            "koordinat bicimi", coordinate_format, COORDINATE_FORMATS
        )

    row = _pref_row(session)
    if row is None:
        defaults = settings_defaults(settings)
        row = UserPreference(
            preference_key=PREFERENCE_KEY,
            language=defaults["language"],
            theme=defaults["theme"],
            timezone=defaults["timezone"],
            coordinate_format=defaults["coordinate_format"],
        )
        session.add(row)
        session.flush()

    if language is not None:
        row.language = language  # type: ignore[assignment]
    if theme is not None:
        row.theme = theme  # type: ignore[assignment]
    if timezone is not None:
        row.timezone = timezone  # type: ignore[assignment]
    if coordinate_format is not None:
        row.coordinate_format = coordinate_format  # type: ignore[assignment]
    row.updated_at = utc_now()  # type: ignore[assignment]
    session.flush()
    return get_preferences(session, settings)


def reset_preferences(session: Session, settings: Any) -> dict[str, Any]:
    """Drop any saved profile so the panel reverts to the settings defaults.

    Deleting the row (rather than rewriting the columns) means the next read
    again reports ``source == settings_default``, which is the honest signal
    that nothing custom is stored any more.
    """
    row = _pref_row(session)
    if row is not None:
        session.delete(row)
        session.flush()
    return get_preferences(session, settings)


def preference_config(settings: Any) -> dict[str, Any]:
    """Descriptive payload: allowed value sets, defaults and the fixed key."""
    return {
        "preference_key": PREFERENCE_KEY,
        "fields": ["language", "theme", "timezone", "coordinate_format"],
        "allowed": {
            "language": list(SUPPORTED_LANGUAGES),
            "theme": list(THEMES),
            "timezone": list(SUPPORTED_TIMEZONES),
            "coordinate_format": list(COORDINATE_FORMATS),
        },
        "defaults": settings_defaults(settings),
        "sources": [
            "user_preferences (saved profile, EM-088)",
            "i18n catalogue (languages, EM-068)",
            "localization (time zone / coordinate format, EM-063)",
        ],
        "attribution": PREFERENCE_ATTRIBUTION,
        "persistence": PREFERENCE_PERSISTENCE,
    }


__all__ = [
    "PREFERENCE_ATTRIBUTION",
    "PREFERENCE_PERSISTENCE",
    "THEMES",
    "UserPreferenceError",
    "get_preferences",
    "preference_config",
    "reset_preferences",
    "settings_defaults",
    "update_preferences",
]
