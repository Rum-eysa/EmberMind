"""EM-088 persisted operator preference profile tests (Epic E8).

The profile turns the ephemeral language (EM-068) / display (EM-063) / theme
knobs into one saved operator-wide row. These tests pin: the settings-derived
default on an empty store (never written until an explicit change), the
partial-update semantics (supplied fields validated and persisted, others kept),
validation of every field against the value sets the rest of the system honours,
the reset-to-default dropping the row so the next read is ``settings_default``
again, the ``config`` payload, and the HTTP endpoints (GET defaults, PUT save +
400 on a bad value, DELETE reset, config).
"""
import pytest

from src.services.user_preferences import (
    PREFERENCE_ATTRIBUTION,
    PREFERENCE_PERSISTENCE,
    THEMES,
    UserPreferenceError,
    get_preferences,
    preference_config,
    reset_preferences,
    settings_defaults,
    update_preferences,
)


class _Settings:
    """Settings-derived defaults for the four display knobs."""

    def __init__(
        self,
        *,
        language="tr",
        theme="dark",
        timezone="Europe/Istanbul",
        coordinate_format="decimal",
    ):
        self.I18N_DEFAULT_LANGUAGE = language
        self.UI_DEFAULT_THEME = theme
        self.DISPLAY_TIMEZONE = timezone
        self.DISPLAY_COORDINATE_FORMAT = coordinate_format


def _prefs(session, settings=None):
    return get_preferences(session, settings or _Settings())


# --------------------------------------------------------------------------
# default-then-persist lifecycle
# --------------------------------------------------------------------------
def test_empty_read_reports_settings_default_without_storing(session):
    session.flush()
    data = _prefs(session)
    assert data["source"] == "settings_default"
    assert data["preference_key"] == "default"
    assert data["language"] == "tr"
    assert data["theme"] == "dark"
    assert data["timezone"] == "Europe/Istanbul"
    assert data["coordinate_format"] == "decimal"
    assert data["updated_at"] is None
    # Nothing should have been persisted on a pure read.
    assert get_preferences(session, _Settings())["source"] == "settings_default"


def test_defaults_are_derived_from_settings():
    assert settings_defaults(_Settings(language="el", theme="light")) == {
        "language": "el",
        "theme": "light",
        "timezone": "Europe/Istanbul",
        "coordinate_format": "decimal",
    }


def test_out_of_range_setting_falls_back_to_safe_default():
    # An unknown configured language / theme must not leak into the profile.
    defaults = settings_defaults(_Settings(language="zz", theme="neon"))
    assert defaults["language"] == "tr"
    assert defaults["theme"] == "dark"


# --------------------------------------------------------------------------
# update (partial) semantics + validation
# --------------------------------------------------------------------------
def test_update_persists_and_flips_source_to_stored(session):
    out = update_preferences(session, _Settings(), language="en")
    session.flush()
    assert out["source"] == "stored"
    assert out["language"] == "en"
    # unsupplied fields keep the settings default
    assert out["theme"] == "dark"
    assert out["coordinate_format"] == "decimal"
    # the row now exists independently of the read
    assert get_preferences(session, _Settings())["language"] == "en"


def test_update_is_partial_and_cumulative(session):
    update_preferences(session, _Settings(), theme="light")
    update_preferences(session, _Settings(), timezone="Europe/Athens")
    session.flush()
    data = _prefs(session)
    assert data["theme"] == "light"
    assert data["timezone"] == "Europe/Athens"
    assert data["language"] == "tr"


def test_update_rejects_unknown_language(session):
    with pytest.raises(UserPreferenceError):
        update_preferences(session, _Settings(), language="fr")


def test_update_rejects_unknown_theme(session):
    with pytest.raises(UserPreferenceError):
        update_preferences(session, _Settings(), theme="sepia")


def test_update_rejects_unknown_timezone(session):
    with pytest.raises(UserPreferenceError):
        update_preferences(session, _Settings(), timezone="Mars/Olympus")


def test_update_rejects_unknown_coordinate_format(session):
    with pytest.raises(UserPreferenceError):
        update_preferences(session, _Settings(), coordinate_format="degrees")


# --------------------------------------------------------------------------
# reset to default
# --------------------------------------------------------------------------
def test_reset_drops_the_row_back_to_settings_default(session):
    update_preferences(session, _Settings(), language="en", theme="light")
    session.flush()
    assert _prefs(session)["source"] == "stored"
    out = reset_preferences(session, _Settings())
    session.flush()
    assert out["source"] == "settings_default"
    assert out["language"] == "tr"
    assert out["theme"] == "dark"


def test_reset_on_empty_store_is_idempotent(session):
    out = reset_preferences(session, _Settings())
    session.flush()
    assert out["source"] == "settings_default"


# --------------------------------------------------------------------------
# config payload
# --------------------------------------------------------------------------
def test_config_exposes_allowed_sets_and_defaults():
    cfg = preference_config(_Settings())
    assert cfg["preference_key"] == "default"
    assert set(cfg["fields"]) == {
        "language",
        "theme",
        "timezone",
        "coordinate_format",
    }
    assert "tr" in cfg["allowed"]["language"]
    assert list(THEMES) == cfg["allowed"]["theme"]
    assert "Europe/Athens" in cfg["allowed"]["timezone"]
    assert "dms" in cfg["allowed"]["coordinate_format"]
    assert cfg["defaults"]["language"] == "tr"
    assert cfg["persistence"] == PREFERENCE_PERSISTENCE
    assert cfg["attribution"] == PREFERENCE_ATTRIBUTION


# --------------------------------------------------------------------------
# HTTP endpoints
# --------------------------------------------------------------------------
def test_endpoint_get_defaults(api, client, session):
    session.commit()
    body = client.get("/api/v1/preferences").json()
    assert body["source"] in ("settings_default", "stored")
    assert body["language"] in ("tr", "en", "el")


def test_endpoint_put_then_get_and_delete(api, client, session):
    session.commit()
    resp = client.put("/api/v1/preferences", json={"language": "en", "theme": "light"})
    assert resp.status_code == 200
    assert resp.json()["language"] == "en"
    assert resp.json()["source"] == "stored"
    assert client.get("/api/v1/preferences").json()["theme"] == "light"
    reset = client.delete("/api/v1/preferences")
    assert reset.status_code == 200
    assert reset.json()["source"] == "settings_default"


def test_endpoint_put_invalid_is_400(api, client, session):
    session.commit()
    resp = client.put("/api/v1/preferences", json={"theme": "neon"})
    assert resp.status_code == 400


def test_endpoint_config(api, client):
    resp = client.get("/api/v1/preferences/config")
    assert resp.status_code == 200
    assert resp.json()["preference_key"] == "default"
