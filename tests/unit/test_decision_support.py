"""EM-097 decision-support framing tests (Epic E10).

The commander must always see, on the recommendation screen, that EmberMind is a
*decision support* tool (the final decision belongs to the authorised operator),
which data / model version produced the advice, and an unmissable
``SENARYO VERİSİ`` badge when the pilot runs on synthetic data. These tests pin
the defaults, settings overrides (with blank/whitespace falling back), the
scenario-data badge toggle, the config shape and the read-only HTTP endpoints.
"""
from src.services.decision_support import (
    DEFAULT_DATA_VERSION,
    DEFAULT_MODEL_VERSION,
    DEFAULT_RESPONSIBILITY_TEXT,
    REAL_DATA_NOTICE,
    SCENARIO_BADGE_LABEL,
    SUPPORT_PERSISTENCE,
    support_config,
    support_framing,
)


class _Settings:
    """Minimal settings stub; the service defaults every knob via ``getattr``."""

    def __init__(self, **overrides: object) -> None:
        for key, value in overrides.items():
            setattr(self, key, value)


# --------------------------------------------------------------------------- #
# Framing defaults
# --------------------------------------------------------------------------- #
def test_framing_defaults_are_advisory_only():
    framing = support_framing(_Settings())
    assert framing["advisory_only"] is True
    assert framing["decision_owner"] == "yetkili operatör"
    assert framing["responsibility_statement"] == DEFAULT_RESPONSIBILITY_TEXT
    assert "karar" in framing["responsibility_statement"].lower()


def test_framing_defaults_versions_and_persistence():
    framing = support_framing(_Settings())
    assert framing["model_version"] == DEFAULT_MODEL_VERSION
    assert framing["data_version"] == DEFAULT_DATA_VERSION
    assert framing["persistence"] == SUPPORT_PERSISTENCE


def test_framing_default_scenario_badge_is_visible():
    framing = support_framing(_Settings())
    assert framing["scenario_data"] is True
    assert framing["scenario_badge"] == SCENARIO_BADGE_LABEL
    assert framing["scenario_notice"] != REAL_DATA_NOTICE


# --------------------------------------------------------------------------- #
# Settings overrides
# --------------------------------------------------------------------------- #
def test_framing_honours_settings_overrides():
    settings = _Settings(
        DECISION_SUPPORT_MODEL_VERSION="spread-v2",
        DECISION_SUPPORT_DATA_VERSION="real-2026.09",
        DECISION_SUPPORT_RESPONSIBILITY_TEXT="Karar operatöründür.",
    )
    framing = support_framing(settings)
    assert framing["model_version"] == "spread-v2"
    assert framing["data_version"] == "real-2026.09"
    assert framing["responsibility_statement"] == "Karar operatöründür."


def test_framing_blank_override_falls_back_to_default():
    settings = _Settings(
        DECISION_SUPPORT_MODEL_VERSION="   ",
        DECISION_SUPPORT_RESPONSIBILITY_TEXT="",
    )
    framing = support_framing(settings)
    assert framing["model_version"] == DEFAULT_MODEL_VERSION
    assert framing["responsibility_statement"] == DEFAULT_RESPONSIBILITY_TEXT


def test_framing_scenario_off_hides_badge():
    settings = _Settings(DECISION_SUPPORT_SCENARIO_DATA=False)
    framing = support_framing(settings)
    assert framing["scenario_data"] is False
    assert framing["scenario_badge"] is None
    assert framing["scenario_notice"] == REAL_DATA_NOTICE


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_config_shape_and_framing_match():
    settings = _Settings()
    config = support_config(settings)
    assert config["framing"] == support_framing(settings)
    assert config["persistence"] == SUPPORT_PERSISTENCE
    assert config["labels"]["scenario_badge"] == SCENARIO_BADGE_LABEL
    assert "DECISION_SUPPORT_MODEL_VERSION" in config["editable_settings"]
    assert "EM-097" in config["attribution"]


def test_config_defaults_are_exposed():
    config = support_config(_Settings())
    assert config["defaults"]["model_version"] == DEFAULT_MODEL_VERSION
    assert config["defaults"]["responsibility_text"] == DEFAULT_RESPONSIBILITY_TEXT


# --------------------------------------------------------------------------- #
# HTTP endpoints (read-only)
# --------------------------------------------------------------------------- #
def test_endpoint_framing(client):
    resp = client.get("/api/v1/decision-support")
    assert resp.status_code == 200
    body = resp.json()
    assert body["advisory_only"] is True
    assert body["responsibility_statement"]
    assert body["model_version"] == DEFAULT_MODEL_VERSION
    assert body["scenario_badge"] == SCENARIO_BADGE_LABEL


def test_endpoint_config(client):
    resp = client.get("/api/v1/decision-support/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["framing"]["decision_owner"] == "yetkili operatör"
    assert "DECISION_SUPPORT_SCENARIO_DATA" in body["editable_settings"]
