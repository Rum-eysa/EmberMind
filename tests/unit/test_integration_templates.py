"""EM-093 municipality / traffic / public-alert integration template tests (Epic E9).

An integrator wants to connect *existing* downstream equipment - a municipality
information board, a traffic variable-message sign, a CAP-style public-alert
head-end - to the EM-094 signed webhook without new hardware. These tests pin
the pure read-time projection: the channel catalog derived from the live EM-094
contract, the per-channel reshape of a sample envelope, the VMS character
clipping, the CAP-style rendering, and the security posture (the shared-secret
is referenced only through an environment placeholder, never embedded). They
also verify the endpoints answer and that the paths are published in OpenAPI.
"""
import pytest

from src.services.integration_templates import (
    CHANNEL_IDS,
    SECRET_PLACEHOLDER,
    TEMPLATES_PERSISTENCE,
    VMS_MAX_CHARS_PER_LINE,
    IntegrationTemplateError,
    _clip,
    example_consumer,
    example_envelope,
    integration_config,
    templates_bundle,
    templates_for,
    transform,
)
from src.services.webhook_delivery import SIGNATURE_HEADER, VALID_EVENT_TYPES


class _Settings:
    """Minimal settings stub; the service defaults every knob via ``getattr``."""

    def __init__(self, **overrides: object) -> None:
        for key, value in overrides.items():
            setattr(self, key, value)


# --------------------------------------------------------------------------- #
# integration_config
# --------------------------------------------------------------------------- #
def test_config_catalog_and_contract():
    cfg = integration_config(_Settings())
    ids = [channel["id"] for channel in cfg["channels"]]
    assert ids == list(CHANNEL_IDS)
    assert "municipality_board" in ids
    assert "traffic_vms" in ids
    assert "public_alert" in ids
    assert cfg["event_types"] == list(VALID_EVENT_TYPES)
    assert cfg["signature_header"] == SIGNATURE_HEADER
    assert cfg["no_new_hardware"] is True
    assert cfg["persistence"] == TEMPLATES_PERSISTENCE
    assert "EM-093" in cfg["attribution"]


def test_config_sender_and_language_defaults():
    cfg = integration_config(_Settings())
    assert cfg["cap_sender"] == "it.embermind.wildfire"
    assert cfg["alert_language"] == "tr"


def test_config_sender_and_language_overridable():
    cfg = integration_config(
        _Settings(
            INTEGRATION_CAP_SENDER="it.regione.alpha", INTEGRATION_ALERT_LANGUAGE="el"
        )
    )
    assert cfg["cap_sender"] == "it.regione.alpha"
    assert cfg["alert_language"] == "el"


def test_config_blank_values_fall_back():
    cfg = integration_config(
        _Settings(INTEGRATION_CAP_SENDER="  ", INTEGRATION_ALERT_LANGUAGE="")
    )
    assert cfg["cap_sender"] == "it.embermind.wildfire"
    assert cfg["alert_language"] == "tr"


# --------------------------------------------------------------------------- #
# example_envelope
# --------------------------------------------------------------------------- #
def test_example_envelope_shape():
    env = example_envelope("alert")
    assert env["event_type"] == "alert"
    notification = env["notification"]
    assert notification["kind"] == "alert"
    assert notification["title"]
    assert notification["payload"]["region"]


def test_example_envelope_unknown_kind_raises():
    with pytest.raises(IntegrationTemplateError):
        example_envelope("bogus")


# --------------------------------------------------------------------------- #
# transform per channel
# --------------------------------------------------------------------------- #
def test_transform_municipality_board():
    rendered = transform(example_envelope("alert"), "municipality_board", _Settings())
    assert rendered["channel"] == "municipality_board"
    body = rendered["render"]
    assert body["severity"] == "emergency"
    assert body["area"] == "Pilot Bölge A"
    assert body["source"] == "EmberMind"


def test_transform_traffic_vms_alert_uppercases_and_flashes():
    rendered = transform(example_envelope("alert"), "traffic_vms", _Settings())
    body = rendered["render"]
    assert body["line1"].isupper()
    assert body["flash"] is True
    assert body["closure_hint"] is True
    assert body["max_chars_per_line"] == VMS_MAX_CHARS_PER_LINE


def test_transform_traffic_vms_forecast_no_flash():
    rendered = transform(example_envelope("forecast"), "traffic_vms", _Settings())
    body = rendered["render"]
    assert body["flash"] is False
    assert body["closure_hint"] is False


def test_transform_public_alert_cap_like():
    rendered = transform(example_envelope("alert"), "public_alert", _Settings())
    assert rendered["render"]["sender"] == "it.embermind.wildfire"
    assert rendered["render"]["severity"] == "emergency"
    assert "<alert>" in rendered["cap_xml_example"]
    assert "areaDesc" in rendered["cap_xml_example"]


def test_transform_records_event_type():
    rendered = transform(
        example_envelope("fire_event"), "municipality_board", _Settings()
    )
    assert rendered["event_type"] == "fire_event"


def test_transform_unknown_channel_raises():
    with pytest.raises(IntegrationTemplateError):
        transform(example_envelope("alert"), "smoke_signal", _Settings())


def test_transform_missing_notification_raises():
    with pytest.raises(IntegrationTemplateError):
        transform({"event_type": "alert"}, "municipality_board", _Settings())


def test_transform_non_dict_envelope_raises():
    with pytest.raises(IntegrationTemplateError):
        transform("not-an-envelope", "municipality_board", _Settings())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# _clip
# --------------------------------------------------------------------------- #
def test_clip_short_text_unchanged_uppercased():
    assert _clip("risk yuksek") == "RISK YUKSEK"


def test_clip_long_text_truncated_within_limit():
    out = _clip("A" * 200, limit=20)
    assert len(out) <= 20
    assert out.endswith("..")


# --------------------------------------------------------------------------- #
# templates_for / bundle
# --------------------------------------------------------------------------- #
def test_templates_for_all_channels():
    bundle = templates_for("alert", _Settings())
    assert bundle["event_type"] == "alert"
    assert bundle["signature_header"] == SIGNATURE_HEADER
    channels = [t["channel"] for t in bundle["templates"]]
    assert channels == list(CHANNEL_IDS)
    assert bundle["sample_envelope"]["notification"]["kind"] == "alert"


def test_templates_for_unknown_kind_raises():
    with pytest.raises(IntegrationTemplateError):
        templates_for("bogus", _Settings())


def test_templates_bundle_shape():
    bundle = templates_bundle(_Settings())
    assert set(bundle) >= {"config", "by_channel", "consumer"}
    assert set(bundle["by_channel"]) == set(VALID_EVENT_TYPES)
    assert "EM-093" in bundle["attribution"]


# --------------------------------------------------------------------------- #
# example_consumer
# --------------------------------------------------------------------------- #
def test_example_consumer_uses_env_placeholder_not_a_secret():
    consumer = example_consumer(_Settings())
    assert consumer["secret_env"] == "EMBERMIND_WEBHOOK_SECRET"
    assert consumer["signature_header"] == SIGNATURE_HEADER
    assert "hmac" in consumer["verify_snippet"]
    # The placeholder is only a name; no concrete secret value is ever embedded.
    assert SECRET_PLACEHOLDER in str(integration_config(_Settings()))


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_bundle_endpoint(client):
    resp = client.get("/api/v1/integration-templates")
    assert resp.status_code == 200
    body = resp.json()
    assert "EM-093" in body["attribution"]
    assert body["config"]["no_new_hardware"] is True


def test_config_endpoint_uses_testing_overrides(client):
    resp = client.get("/api/v1/integration-templates/config")
    assert resp.status_code == 200
    body = resp.json()
    # TestingConfig pins a deterministic sender so template output is stable.
    assert body["cap_sender"] == "it.embermind.test"
    assert [c["id"] for c in body["channels"]] == list(CHANNEL_IDS)


def test_consumer_endpoint(client):
    resp = client.get("/api/v1/integration-templates/consumer")
    assert resp.status_code == 200
    assert "hmac" in resp.json()["verify_snippet"]


def test_by_event_type_endpoint(client):
    resp = client.get("/api/v1/integration-templates/alert")
    assert resp.status_code == 200
    assert len(resp.json()["templates"]) == len(CHANNEL_IDS)


def test_by_event_type_unknown(client):
    resp = client.get("/api/v1/integration-templates/bogus")
    assert resp.status_code == 200
    assert "error" in resp.json()


def test_by_channel_endpoint(client):
    resp = client.get("/api/v1/integration-templates/alert/traffic_vms")
    assert resp.status_code == 200
    assert resp.json()["channel"] == "traffic_vms"


def test_by_channel_unknown_channel(client):
    resp = client.get("/api/v1/integration-templates/alert/smoke_signal")
    assert resp.status_code == 200
    assert "error" in resp.json()


def test_integration_templates_published_in_openapi(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/v1/integration-templates" in paths
    assert "/api/v1/integration-templates/config" in paths
