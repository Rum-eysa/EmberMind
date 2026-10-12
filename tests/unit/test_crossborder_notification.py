"""EM-069 joint cross-border early-warning notification tests.

The EM-067 projection says *a fire could reach the border*; EM-069 turns that
into a partner warning once an agreed likelihood + lead-time threshold passes,
over a pre-defined channel. These tests seed active incidents with head bearings
that drive at the border and assert the threshold gate, the edge-triggered
deduplication, the auto-resolve lifecycle and the persisted dispatch log.
"""
from src.models.spatial import FireEvent, FireForecast
from src.services.crossborder_notification import (
    NOTIF_OPEN,
    NOTIF_RESOLVED,
    NotificationError,
    channel_for,
    dispatch,
    evaluate_thresholds,
    list_notifications,
    notification_status,
    sweep,
)
from src.utils.timeutils import utc_now

_KM_PER_DEG_LON = 111.320


class _Settings:
    """Default pilot border (26.5), 30/60/120 window, 0.4 likelihood gate."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]


class _HighGate(_Settings):
    """Only a near-certain (>=0.95) toward-border movement warrants a warning."""

    CROSSBORDER_NOTIFY_MIN_LIKELIHOOD = 0.95


class _WideWindow(_Settings):
    """A far-off crossing still counts when the lead-time window is widened."""

    CROSSBORDER_NOTIFY_WINDOW_MINUTES = 500


def _event(session, key, longitude, latitude=38.0):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} yayilim",
            latitude=latitude,
            longitude=longitude,
            min_lat=latitude - 0.05,
            max_lat=latitude + 0.05,
            min_lon=longitude - 0.05,
            max_lon=longitude + 0.05,
            geometry_wkt=f"POINT({longitude} {latitude})",
            status="active",
            started_at=utc_now().replace(tzinfo=None),
        )
    )


def _forecast(session, key, direction_deg, ros_m_min):
    session.add(
        FireForecast(
            event_key=key,
            model_name="rothermel_v1",
            latitude=38.0,
            longitude=27.5,
            predicted_area_ha=10.0,
            geometry_wkt="POLYGON((27 38,27.01 38,27.01 38.01,27 38.01,27 38))",
            forecast_for=utc_now(),
            horizon_minutes=120,
            rate_of_spread_m_per_min=ros_m_min,
            spread_direction_deg=direction_deg,
            inputs_json="{}",
        )
    )


def _qual_keys(evaluation):
    return {row["event_key"]: row for row in evaluation["qualifying"]}


# --------------------------------------------------------------------------
# threshold gate
# --------------------------------------------------------------------------
def test_qualifying_crossing_toward_partner(session):
    _event(session, "EVT-W", 27.5)  # TR side, head due west -> GR border.
    _forecast(session, "EVT-W", 270.0, 1000.0)
    session.flush()
    qual = _qual_keys(evaluate_thresholds(session, _Settings()))
    assert "EVT-W" in qual
    assert qual["EVT-W"]["target_country"] == "GR"
    assert qual["EVT-W"]["likelihood"] == 1.0
    assert qual["EVT-W"]["recipient"]  # pre-defined channel filled


def test_low_likelihood_excluded(session):
    # A partly-aimed head (315 deg = cos45 ~ 0.71 share) fast enough to clear
    # the lead-time window: it passes the 0.4 gate but fails a 0.95 gate.
    _event(session, "EVT-SLANT", 27.5)
    _forecast(session, "EVT-SLANT", 315.0, 4000.0)
    session.flush()
    qual = _qual_keys(evaluate_thresholds(session, _Settings()))
    assert "EVT-SLANT" in qual
    strict = _qual_keys(evaluate_thresholds(session, _HighGate()))
    assert "EVT-SLANT" not in strict


def test_window_exclusion_and_override(session):
    _event(session, "EVT-NEAR", 27.5)
    _forecast(session, "EVT-NEAR", 270.0, 1000.0)  # ~87.7 min
    session.flush()
    assert "EVT-NEAR" in _qual_keys(evaluate_thresholds(session, _Settings()))


def test_far_crossing_out_of_default_window(session):
    _event(session, "EVT-FAR", 27.5)
    _forecast(session, "EVT-FAR", 270.0, 200.0)  # ~438 min > 120
    session.flush()
    assert "EVT-FAR" not in _qual_keys(evaluate_thresholds(session, _Settings()))
    assert "EVT-FAR" in _qual_keys(evaluate_thresholds(session, _WideWindow()))


def test_moving_away_not_projected(session):
    _event(session, "EVT-E", 27.5)
    _forecast(session, "EVT-E", 90.0, 1000.0)  # due east, away from the border
    session.flush()
    assert "EVT-E" not in _qual_keys(evaluate_thresholds(session, _Settings()))


# --------------------------------------------------------------------------
# dispatch + edge-triggered dedup
# --------------------------------------------------------------------------
def test_channel_for_target(session):
    assert channel_for("GR")["channel"] == "gr-general-secretariat-kanali"
    assert channel_for("TR")["channel"] == "tr-mobil-birim-kanali"


def test_channel_unknown_country_raises(session):
    try:
        channel_for("XX")
        raise AssertionError("expected NotificationError")
    except NotificationError:
        pass


def test_dispatch_creates_record(session):
    result = dispatch(session, _Settings(), "EVT-W", "GR")
    assert result["created"] is True
    notif = result["notification"]
    assert notif["status"] == NOTIF_OPEN
    assert notif["target_country"] == "GR"
    assert notif["source_country"] == "TR"
    assert notif["recipient"]


def test_dispatch_is_deduped(session):
    first = dispatch(session, _Settings(), "EVT-W", "GR")
    second = dispatch(session, _Settings(), "EVT-W", "GR")
    assert first["created"] is True
    assert second["created"] is False and second["deduped"] is True
    rows = list_notifications(session, event_key="EVT-W")
    assert len(rows) == 1


# --------------------------------------------------------------------------
# sweep: create, dedup, auto-resolve
# --------------------------------------------------------------------------
def test_sweep_dispatches_qualifying(session):
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 1000.0)
    session.flush()
    result = sweep(session, _Settings())
    assert len(result["created"]) == 1
    assert result["created"][0]["target_country"] == "GR"


def test_sweep_dedups_on_rerun(session):
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 1000.0)
    session.flush()
    sweep(session, _Settings())
    second = sweep(session, _Settings())
    assert second["created"] == []
    assert len(second["deduped"]) == 1


def test_sweep_resolves_when_no_longer_projected(session):
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 1000.0)
    session.flush()
    sweep(session, _Settings())
    # The head turns away, so the crossing is no longer projected.
    _forecast(session, "EVT-W", 90.0, 1000.0)
    session.flush()
    result = sweep(session, _Settings())
    assert len(result["resolved"]) == 1
    assert result["resolved"][0]["status"] == NOTIF_RESOLVED


def test_gr_side_targets_tr(session):
    _event(session, "EVT-GR", 25.5)  # west of the border -> GR, head due east.
    _forecast(session, "EVT-GR", 90.0, 1000.0)
    session.flush()
    qual = _qual_keys(evaluate_thresholds(session, _Settings()))
    assert qual["EVT-GR"]["source_country"] == "GR"
    assert qual["EVT-GR"]["target_country"] == "TR"


def test_status_reports_notified(session):
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 1000.0)
    session.flush()
    before = notification_status(session, _Settings())
    assert before["qualifying"][0]["notified"] is False
    sweep(session, _Settings())
    after = notification_status(session, _Settings())
    assert after["qualifying"][0]["notified"] is True
    assert after["summary"]["crossings_qualifying"] == 1


# --------------------------------------------------------------------------
# HTTP feed
# --------------------------------------------------------------------------
def _seed_crossing(session):
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 1000.0)
    session.commit()


def test_endpoint_config(client):
    resp = client.get("/api/v1/crossborder/notifications/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["edge_triggered"] is True
    assert body["persistence"] == "crossborder_notification"


def test_endpoint_status_empty(client):
    resp = client.get("/api/v1/crossborder/notification-status")
    assert resp.status_code == 200
    assert resp.json()["qualifying"] == []


def test_endpoint_sweep_dispatches(client, session):
    _seed_crossing(session)
    resp = client.post("/api/v1/crossborder/notifications/sweep")
    assert resp.status_code == 200
    assert len(resp.json()["created"]) == 1
    log = client.get("/api/v1/crossborder/notifications")
    assert log.status_code == 200
    assert log.json()["count"] == 1


def test_endpoint_dispatch_bad_target_400(client):
    resp = client.post(
        "/api/v1/crossborder/notifications?event_key=EVT-X&target_country=XX"
    )
    assert resp.status_code == 400
