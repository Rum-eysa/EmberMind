"""EM-079 panel-state catalogue tests (Epic E8).

The catalogue is the single deterministic source of every operator panel's
loading / empty / error copy plus the connection-lost band. These tests pin the
invariants the acceptance criteria demand: each panel carries all four states,
every error names both what happened and what to do, the connection band is
present, and the read-only HTTP endpoints answer 200 / 404 correctly.
"""
import pytest

from src.services.ui_states import (
    CONNECTION_LOST,
    PANEL_KEYS,
    PANEL_STATES,
    UI_STATE_ATTRIBUTION,
    UI_STATE_PERSISTENCE,
    connection_state,
    panel_state,
    panel_states_by_key,
    ui_state_catalog,
)

# An actionable error must carry a verb telling the operator what to do.
ACTIONABLE_HINTS = ("deneyin", "kontrol", "seçin", "gözden", "sıfırlayın", "emin")


# --------------------------------------------------------------------------- #
# Catalogue shape
# --------------------------------------------------------------------------- #
def test_every_panel_declares_all_four_states():
    catalog = ui_state_catalog()
    assert len(catalog["panels"]) == len(PANEL_KEYS)
    for panel in catalog["panels"]:
        for field in ("loading", "empty", "error", "error_action", "title"):
            assert panel[field].strip(), f"{panel['key']}.{field} boş"


def test_panel_keys_cover_the_operator_surfaces():
    # The panels the map + command deck actually render.
    for key in ("map_layers", "exposure", "positioning", "silent_zones"):
        assert key in PANEL_KEYS
        assert key in PANEL_STATES


def test_error_message_names_the_failure_and_the_action():
    for panel in ui_state_catalog()["panels"]:
        # "what happened" line is non-empty ...
        assert panel["error"]
        # ... and the action line tells the operator something concrete to do.
        action = panel["error_action"].lower()
        assert any(hint in action for hint in ACTIONABLE_HINTS), panel["key"]


def test_connection_band_is_present_and_actionable():
    connection = ui_state_catalog()["connection"]
    assert connection["title"] == CONNECTION_LOST["title"] == "Bağlantı kesildi"
    assert connection["text"]
    assert connection["retry_label"]
    assert connection["auto_reconnect"] is True


def test_catalog_metadata():
    catalog = ui_state_catalog()
    assert catalog["catalog"] == "ui_states"
    assert catalog["language"] == "tr"
    assert catalog["attribution"] == UI_STATE_ATTRIBUTION
    assert catalog["persistence"] == UI_STATE_PERSISTENCE == "none"


def test_catalog_language_honours_settings():
    class _Settings:
        UI_STATE_LANGUAGE = "en"

    assert ui_state_catalog(_Settings())["language"] == "en"


# --------------------------------------------------------------------------- #
# Single-panel access
# --------------------------------------------------------------------------- #
def test_panel_state_returns_copy():
    state = panel_state("silent_zones")
    assert state["key" if "key" in state else "title"]  # has a title
    # mutating the returned dict must not touch the catalogue
    state["loading"] = "değiştirildi"
    assert PANEL_STATES["silent_zones"]["loading"] != "değiştirildi"


def test_panel_state_unknown_key_raises():
    with pytest.raises(LookupError):
        panel_state("does_not_exist")


def test_panel_states_by_key_shape():
    mapping = panel_states_by_key()
    assert set(mapping) == set(PANEL_KEYS)
    assert mapping["exposure"]["empty"] == PANEL_STATES["exposure"]["empty"]


# --------------------------------------------------------------------------- #
# Connection-state payload
# --------------------------------------------------------------------------- #
def test_connection_state_lost_carries_band():
    payload = connection_state(True, detail="socket closed")
    assert payload["lost"] is True
    assert payload["detail"] == "socket closed"
    assert payload["band"] is not None
    assert payload["text"] == CONNECTION_LOST["text"]


def test_connection_state_recovered_clears_band():
    payload = connection_state(False)
    assert payload["lost"] is False
    assert payload["band"] is None
    assert payload["detail"] is None
    assert "geldi" in payload["text"]


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_catalog(client):
    resp = client.get("/api/v1/ui-states")
    assert resp.status_code == 200
    body = resp.json()
    assert body["catalog"] == "ui_states"
    assert len(body["panels"]) == len(PANEL_KEYS)
    assert body["connection"]["title"] == "Bağlantı kesildi"


def test_endpoint_single_panel(client):
    resp = client.get("/api/v1/ui-states/panel/map_layers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error_action"]  # actionable


def test_endpoint_unknown_panel_404(client):
    resp = client.get("/api/v1/ui-states/panel/nope")
    assert resp.status_code == 404
