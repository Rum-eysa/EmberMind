"""EM-086 notification centre + audible-alert settings tests (Epic E8).

The centre layers read / acknowledge state and a single operator-wide audible
configuration on top of the live-feed ``alert`` rows (EM-032/EM-090) without
duplicating the alert content. These tests pin: the newest-first listing with
per-alert read/unread state, the ``requires_ack`` ladder (critical bands pin
until acknowledged - reading alone does not clear them), the mark-read /
acknowledge / read-all mutations, the audible default-then-persist lifecycle,
the ``should_sound`` level gate, the summary counts and the HTTP endpoints
(including the 404 on an unknown alert).
"""
import json

from src.models.live import LiveUpdate
from src.services.notification_center import (
    ACK_REQUIRED_LEVELS,
    NOTIFICATION_ATTRIBUTION,
    NOTIFICATION_PERSISTENCE,
    NotificationCenterError,
    acknowledge,
    get_sound_setting,
    list_notifications,
    mark_all_read,
    mark_read,
    notification_center_config,
    should_sound,
    update_sound_setting,
)


class _Settings:
    """Audible defaults + window cap used to seed the singleton fallback."""

    def __init__(self, *, max_alerts=100, sound_enabled=True, min_level="dikkat"):
        self.NOTIFICATION_MAX_ALERTS = max_alerts
        self.NOTIFICATION_SOUND_ENABLED = sound_enabled
        self.NOTIFICATION_SOUND_MIN_LEVEL = min_level


def _alert(session, *, level="dikkat", event_key="evt-1", from_level="normal"):
    """Push one ``alert`` onto the live feed and return its id."""
    row = LiveUpdate(
        kind="alert",
        event_key=event_key,
        title=f"Risk yükseldi: {event_key}",
        message=f"{event_key}: {from_level} → {level}",
        source="risk_alert",
        payload_json=json.dumps(
            {"from_level": from_level, "to_level": level, "risk_index": 42}
        ),
    )
    session.add(row)
    session.flush()
    return int(row.id)


# --------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------
def test_empty_window_lists_nothing(session):
    session.flush()
    data = list_notifications(session, _Settings())
    assert data["panel"] == "notification_center"
    assert data["notifications"] == []
    assert data["summary"]["total"] == 0
    assert data["summary"]["unread"] == 0


def test_alerts_listed_newest_first_unread(session):
    first = _alert(session, level="dikkat", event_key="a")
    last = _alert(session, level="kritik", event_key="b")
    session.flush()
    data = list_notifications(session, _Settings())
    ids = [item["live_update_id"] for item in data["notifications"]]
    assert ids == [last, first]
    assert all(item["is_read"] is False for item in data["notifications"])
    assert data["summary"]["total"] == 2
    assert data["summary"]["unread"] == 2


def test_level_and_metadata_projected(session):
    _alert(session, level="kritik-yakin", event_key="x", from_level="dikkat")
    session.flush()
    item = list_notifications(session, _Settings())["notifications"][0]
    assert item["level"] == "kritik-yakin"
    assert item["from_level"] == "dikkat"
    assert item["event_key"] == "x"
    assert item["source"] == "risk_alert"
    assert item["requires_ack"] is True


def test_only_critical_requires_ack(session):
    _alert(session, level="kritik")
    _alert(session, level="kritik-yakin")
    _alert(session, level="dikkat")
    _alert(session, level="normal")
    session.flush()
    data = list_notifications(session, _Settings())
    by_level = {i["level"]: i for i in data["notifications"]}
    for level in ACK_REQUIRED_LEVELS:
        assert by_level[level]["requires_ack"] is True
    assert by_level["dikkat"]["requires_ack"] is False


def test_non_critical_clears_on_read(session):
    aid = _alert(session, level="dikkat")
    session.flush()
    mark_read(session, aid)
    item = list_notifications(session, _Settings())["notifications"][0]
    assert item["is_read"] is True
    assert item["still_showing"] is False


def test_critical_pins_until_acknowledged(session):
    aid = _alert(session, level="kritik")
    session.flush()
    mark_read(session, aid)
    after_read = list_notifications(session, _Settings())["notifications"][0]
    assert after_read["is_read"] is True
    # Reading alone does NOT clear a critical pin (EM-086 acceptance).
    assert after_read["still_showing"] is True
    acknowledge(session, aid)
    after_ack = list_notifications(session, _Settings())["notifications"][0]
    assert after_ack["is_acknowledged"] is True
    assert after_ack["still_showing"] is False


def test_only_active_trims_pinned(session):
    read_plain = _alert(session, level="dikkat", event_key="plain")
    crit = _alert(session, level="kritik", event_key="crit")
    session.flush()
    mark_read(session, read_plain)
    data = list_notifications(session, _Settings(), only_active=True)
    keys = [i["event_key"] for i in data["notifications"]]
    assert keys == ["crit"]
    # summary still describes the whole window.
    assert data["summary"]["total"] == 2


# --------------------------------------------------------------------------
# mutations
# --------------------------------------------------------------------------
def test_mark_read_sets_state(session):
    aid = _alert(session, level="dikkat")
    session.flush()
    state = mark_read(session, aid)
    assert state["is_read"] is True
    assert state["live_update_id"] == aid
    assert state["read_at"] is not None


def test_acknowledge_implies_read(session):
    aid = _alert(session, level="kritik-yakin")
    session.flush()
    state = acknowledge(session, aid)
    assert state["is_acknowledged"] is True
    assert state["is_read"] is True
    assert state["acknowledged_at"] is not None


def test_mark_read_unknown_alert_raises(session):
    session.flush()
    try:
        mark_read(session, 99999)
        raise AssertionError("expected NotificationCenterError")
    except NotificationCenterError as exc:
        assert "bulunamadı" in str(exc)


def test_mark_all_read_marks_window_but_keeps_critical_pin(session):
    _alert(session, level="dikkat", event_key="p1")
    _alert(session, level="kritik", event_key="c1")
    session.flush()
    result = mark_all_read(session, _Settings())
    assert result["marked_read"] == 2
    data = list_notifications(session, _Settings())
    assert data["summary"]["unread"] == 0
    # the critical is read but still pending acknowledgement.
    assert data["summary"]["pending_ack"] == 1


# --------------------------------------------------------------------------
# audible configuration
# --------------------------------------------------------------------------
def test_sound_default_from_settings_then_persisted(session):
    session.flush()
    sound = get_sound_setting(
        session, _Settings(sound_enabled=True, min_level="dikkat")
    )
    assert sound["source"] == "settings_default"
    assert sound["sound_enabled"] is True
    assert sound["min_level"] == "dikkat"
    update_sound_setting(session, _Settings(), sound_enabled=False, min_level="kritik")
    persisted = get_sound_setting(session, _Settings())
    assert persisted["source"] == "stored"
    assert persisted["sound_enabled"] is False
    assert persisted["min_level"] == "kritik"


def test_update_sound_rejects_unknown_level(session):
    session.flush()
    try:
        update_sound_setting(session, _Settings(), min_level="apokaliptik")
        raise AssertionError("expected NotificationCenterError")
    except NotificationCenterError as exc:
        assert "bilinmeyen" in str(exc)


def test_should_sound_level_gate():
    sound = {"sound_enabled": True, "min_level": "dikkat"}
    assert should_sound("dikkat", sound) is True  # boundary inclusive
    assert should_sound("kritik", sound) is True
    assert should_sound("normal", sound) is False  # below the floor
    assert (
        should_sound("kritik", {"sound_enabled": False, "min_level": "dikkat"}) is False
    )


def test_sounding_count_respects_mute(session):
    _alert(session, level="kritik")
    session.flush()
    loud = list_notifications(session, _Settings())
    assert loud["summary"]["sounding"] == 1
    update_sound_setting(session, _Settings(), sound_enabled=False)
    muted = list_notifications(session, _Settings())
    assert muted["summary"]["sounding"] == 0


# --------------------------------------------------------------------------
# config + metadata
# --------------------------------------------------------------------------
def test_config_payload(session):
    cfg = notification_center_config(_Settings())
    assert cfg["levels"][0]["code"] == "normal"
    assert cfg["ack_required_levels"] == list(ACK_REQUIRED_LEVELS)
    assert cfg["default_sound"]["min_level"] == "dikkat"
    assert len(cfg["sources"]) == 3


def test_metadata(session):
    session.flush()
    data = list_notifications(session, _Settings())
    assert data["attribution"] == NOTIFICATION_ATTRIBUTION
    assert data["persistence"] == NOTIFICATION_PERSISTENCE


# --------------------------------------------------------------------------
# HTTP endpoints
# --------------------------------------------------------------------------
def test_endpoint_lists_notifications(api, client, session):
    _alert(session, level="kritik", event_key="e1")
    session.commit()
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total"] == 1
    assert body["notifications"][0]["level"] == "kritik"


def test_endpoint_sound_get_and_put(api, client, session):
    session.commit()
    assert client.get("/api/v1/notifications/sound").json()["min_level"] == "dikkat"
    resp = client.put(
        "/api/v1/notifications/sound",
        json={"sound_enabled": False, "min_level": "kritik"},
    )
    assert resp.status_code == 200
    assert resp.json()["min_level"] == "kritik"
    assert resp.json()["sound_enabled"] is False


def test_endpoint_read_and_acknowledge(api, client, session):
    aid = _alert(session, level="kritik")
    session.commit()
    assert client.post(f"/api/v1/notifications/{aid}/read").status_code == 200
    resp = client.post(f"/api/v1/notifications/{aid}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["is_acknowledged"] is True


def test_endpoint_read_all(api, client, session):
    _alert(session, level="dikkat")
    session.commit()
    resp = client.post("/api/v1/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json()["marked_read"] == 1


def test_endpoint_unknown_alert_is_404(api, client, session):
    session.commit()
    resp = client.post("/api/v1/notifications/424242/read")
    assert resp.status_code == 404


def test_endpoint_config(api, client):
    resp = client.get("/api/v1/notifications/config")
    assert resp.status_code == 200
    assert resp.json()["ack_required_levels"] == list(ACK_REQUIRED_LEVELS)
