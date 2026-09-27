"""EM-090 live-update feed tests: service, REST polling and WebSocket stream."""
from typing import Any

import pytest

from src.services.live import (
    LiveError,
    feed,
    latest_id,
    record_update,
    recent_updates,
    safe_record_update,
)

MANUAL_EVENT: dict[str, Any] = {
    "name": "Canlı Test Olayı",
    "latitude": 37.5,
    "longitude": 28.0,
    "min_lat": 37.4,
    "max_lat": 37.6,
    "min_lon": 27.9,
    "max_lon": 28.1,
    "geometry_wkt": "POLYGON((27.9 37.4, 28.1 37.4, 28.1 37.6, 27.9 37.6, 27.9 37.4))",
    "check_duplicates": False,
    "trigger_prediction": False,
}


class _DisabledSettings:
    """Settings stub with the live feed switched off."""

    LIVE_UPDATES_ENABLED = False


# --------------------------------------------------------------- service ---


def test_record_update_returns_serialized_row(session: Any, api: Any) -> None:
    out = record_update(
        session,
        api.state.settings,
        "fire_event",
        event_key="E1",
        title="Başlık",
        message="gövde",
        payload={"a": 1},
        source="unit",
    )
    assert out is not None
    assert out["id"] >= 1
    assert out["kind"] == "fire_event"
    assert out["event_key"] == "E1"
    assert out["payload"] == {"a": 1}
    assert out["source"] == "unit"


def test_record_update_disabled_returns_none(session: Any) -> None:
    assert record_update(session, _DisabledSettings(), "alert") is None


def test_record_update_rejects_unknown_kind(session: Any, api: Any) -> None:
    with pytest.raises(LiveError):
        record_update(session, api.state.settings, "bogus")


def test_recent_updates_filters_by_since(session: Any, api: Any) -> None:
    settings = api.state.settings
    r1 = record_update(session, settings, "fire_event")
    r2 = record_update(session, settings, "forecast")
    r3 = record_update(session, settings, "alert")
    assert r1 and r2 and r3
    newer = recent_updates(session, r1["id"])
    assert [u["id"] for u in newer] == [r2["id"], r3["id"]]


def test_feed_returns_updates_and_cursor(session: Any, api: Any) -> None:
    settings = api.state.settings
    first = record_update(session, settings, "fire_event")
    last = record_update(session, settings, "alert")
    frame = feed(session, settings, 0)
    assert first and last
    assert frame["count"] == 2
    assert frame["last_id"] == last["id"]
    assert latest_id(session) == last["id"]


def test_latest_id_zero_when_empty(session: Any) -> None:
    assert latest_id(session) == 0


# ------------------------------------------------- safe_record_update ----


def test_safe_record_update_writes_on_its_own_session(api: Any) -> None:
    """Regression: the feed write must not ride on a caller's transaction."""
    safe_record_update(
        api.state.database,
        api.state.settings,
        "fire_event",
        event_key="ISOLOK",
        title="başlık",
    )
    with api.state.database.session() as check:
        assert latest_id(check) >= 1


def test_safe_record_update_swallows_failures(api: Any) -> None:
    """A bad kind raises inside, but the best-effort wrapper must not bubble."""
    safe_record_update(  # does not raise
        api.state.database, api.state.settings, "not-a-real-kind"
    )


def test_safe_record_update_disabled_is_noop(api: Any) -> None:
    safe_record_update(api.state.database, _DisabledSettings(), "fire_event")
    with api.state.database.session() as check:
        assert latest_id(check) == 0


# ------------------------------------------------------------------ REST ---


def test_rest_live_updates_empty(client: Any) -> None:
    body = client.get("/api/v1/live/updates").json()
    assert body["count"] == 0
    assert body["last_id"] == 0
    assert body["updates"] == []


def test_manual_event_emits_fire_event_update(client: Any) -> None:
    created = client.post("/api/v1/events/manual", json=MANUAL_EVENT)
    assert created.status_code == 200
    body = client.get("/api/v1/live/updates?since=0").json()
    kinds = [u["kind"] for u in body["updates"]]
    assert "fire_event" in kinds
    entry = next(u for u in body["updates"] if u["kind"] == "fire_event")
    assert entry["source"] == "manual"
    assert entry["event_key"]


def test_rest_catchup_since_cursor_returns_only_newer(client: Any, api: Any) -> None:
    settings = api.state.settings
    with api.state.database.session() as s:
        first = record_update(s, settings, "fire_event", title="bir")
        second = record_update(s, settings, "alert", title="iki")
    assert first and second
    body = client.get(f"/api/v1/live/updates?since={first['id']}").json()
    ids = [u["id"] for u in body["updates"]]
    assert ids == [second["id"]]
    assert body["last_id"] == second["id"]


# ----------------------------------------------------------- WebSocket ---


def test_ws_snapshot_delivers_existing_updates(client: Any, api: Any) -> None:
    pytest.importorskip("websocket")
    settings = api.state.settings
    with api.state.database.session() as s:
        record_update(s, settings, "fire_event", title="ön", message="mesaj")
    with client.websocket_connect("/ws/live?since=0") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "snapshot"
        assert frame["count"] >= 1
        assert any(u["kind"] == "fire_event" for u in frame["updates"])
        assert frame["last_id"] >= 1


def test_ws_catchup_since_replays_only_missed(client: Any, api: Any) -> None:
    pytest.importorskip("websocket")
    settings = api.state.settings
    with api.state.database.session() as s:
        first = record_update(s, settings, "fire_event", title="eski")
        second = record_update(s, settings, "forecast", title="yeni")
    assert first and second
    with client.websocket_connect(f"/ws/live?since={first['id']}") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "snapshot"
        ids = [u["id"] for u in frame["updates"]]
        assert ids == [second["id"]]


def test_ws_invalid_since_defaults_to_zero(client: Any, api: Any) -> None:
    pytest.importorskip("websocket")
    settings = api.state.settings
    with api.state.database.session() as s:
        record_update(s, settings, "alert", title="tek")
    # A non-numeric cursor must not crash the handshake; it falls back to 0.
    with client.websocket_connect("/ws/live?since=abc") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "snapshot"
        assert frame["count"] >= 1
