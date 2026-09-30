"""EM-057 dynamic plan auto-recompute tests.

Covers the pure change-detection helpers (haversine, per-factor thresholds for
wind / position / capacity), the trigger decision (new plan, debounce, stable,
changed), the feed-backed snapshot loop, the ``forecast`` summary entry the
operator sees and the HTTP endpoints.
"""
from datetime import timedelta

from sqlalchemy import select

from src.models.inventory import SuppressionResource
from src.models.live import LiveUpdate
from src.models.spatial import FireEvent, FireForecast
from src.services.auto_recompute import (
    REASON_CHANGED,
    REASON_DEBOUNCING,
    REASON_NEW_PLAN,
    REASON_STABLE,
    RECOMPUTE_SOURCE,
    auto_recompute_sweep,
    changed_factors,
    current_plan_state,
    evaluate_recompute,
    haversine_km,
    run_recompute,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Driving settings stub for the recompute engine + spread + risk + feed."""

    # Spread engine (EM-015) so run_spread_forecast can produce forecasts.
    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False

    # EM-018 change thresholds (reused for wind/humidity/temp).
    SPREAD_TRIGGER_DEBOUNCE_MINUTES = 15.0
    SPREAD_TRIGGER_WIND_SPEED_KMH_THRESHOLD = 10.0
    SPREAD_TRIGGER_WIND_DIR_DEG_THRESHOLD = 30.0
    SPREAD_TRIGGER_HUMIDITY_PCT_THRESHOLD = 10.0
    SPREAD_TRIGGER_TEMP_C_THRESHOLD = 5.0

    # EM-057.
    AUTO_RECOMPUTE_ENABLED = True
    AUTO_RECOMPUTE_POSITION_MOVE_KM = 1.0
    AUTO_RECOMPUTE_CAPACITY_CHANGE_PCT = 10.0

    # Risk bands (EM-029) + capacity defaults fall back when keys omitted.
    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2

    LIVE_UPDATES_ENABLED = True


def _event(session, key="evt-ar", status="active", lat=38.9, lon=27.5):
    """Persist an active fire event and return it."""
    event = FireEvent(
        event_key=key,
        name="EM-057 Event",
        latitude=lat,
        longitude=lon,
        min_lat=lat - 0.05,
        max_lat=lat + 0.05,
        min_lon=lon - 0.05,
        max_lon=lon + 0.05,
        geometry_wkt=f"POINT({lon} {lat})",
        severity="high",
        status=status,
        started_at=utc_now(),
        source="test",
    )
    session.add(event)
    session.commit()
    return event


def _resource(session, key, rtype="crew", status="available"):
    """Persist one suppression resource (available by default)."""
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key,
            resource_type=rtype,
            latitude=37.0,
            longitude=28.0,
            status=status,
            capacity=1.0,
        )
    )
    session.commit()


def _feed_rows(session, event_key):
    return session.scalars(
        select(LiveUpdate).where(
            LiveUpdate.kind == "forecast",
            LiveUpdate.event_key == event_key,
            LiveUpdate.source == RECOMPUTE_SOURCE,
        )
    ).all()


# ---------------------------------------------------------------------------
# Pure geometry / change-detection helpers
# ---------------------------------------------------------------------------


def test_haversine_zero_distance_and_known_move():
    assert haversine_km(38.9, 27.5, 38.9, 27.5) == 0.0
    # ~0.02 deg of latitude is roughly 2.2 km (well past the 1 km floor).
    assert 1.5 < haversine_km(38.9, 27.5, 38.92, 27.5) < 3.0


def test_changed_factors_empty_without_baseline():
    cur = current_state_stub()
    assert changed_factors({}, cur, _Settings()) == []


def current_state_stub():
    """A stable driving-state snapshot used across the pure tests."""
    return {
        "wind_speed_kmh": 15.0,
        "wind_from_deg": 90.0,
        "relative_humidity_pct": 30.0,
        "air_temp_c": 28.0,
        "latitude": 38.9,
        "longitude": 27.5,
        "capacity_ha_h": 20.0,
    }


def test_changed_factors_detects_each_factor():
    base = current_state_stub()
    settings = _Settings()
    assert changed_factors(base, dict(base), settings) == []
    assert "wind_speed" in changed_factors(
        base, dict(base, wind_speed_kmh=30.0), settings
    )
    assert "wind_dir" in changed_factors(
        base, dict(base, wind_from_deg=180.0), settings
    )
    assert "humidity" in changed_factors(
        base, dict(base, relative_humidity_pct=45.0), settings
    )
    assert "temp" in changed_factors(base, dict(base, air_temp_c=36.0), settings)
    assert "position" in changed_factors(base, dict(base, latitude=38.95), settings)
    assert "capacity" in changed_factors(base, dict(base, capacity_ha_h=10.0), settings)


def test_wind_direction_uses_wraparound():
    base = current_state_stub()
    # 80 -> 100 is a 20-degree move (below the 30-degree floor) -> no change.
    assert "wind_dir" not in changed_factors(
        base, dict(base, wind_from_deg=100.0), _Settings()
    )


# ---------------------------------------------------------------------------
# Trigger decision + feed-backed snapshot loop
# ---------------------------------------------------------------------------


def test_new_event_without_snapshot_recomputes(session):
    event = _event(session)
    decision = evaluate_recompute(session, _Settings(), event)
    assert decision["should_recompute"] is True
    assert decision["reason"] == REASON_NEW_PLAN
    assert decision["changed"] == []


def test_current_plan_state_reads_capacity_and_position(session):
    event = _event(session, lat=39.0, lon=27.0)
    _resource(session, "AR-C1")
    _resource(session, "AR-C2")
    state = current_plan_state(session, _Settings(), event)
    assert state["latitude"] == 39.0
    assert state["longitude"] == 27.0
    # Two crews x 2.0 ha/hour default assumption.
    assert state["capacity_ha_h"] == 4.0


def test_run_recompute_persists_forecast_and_feed_entry(session):
    event = _event(session)
    _resource(session, "AR-C1")
    result = run_recompute(session, _Settings(), event)
    assert result["reason"] == REASON_NEW_PLAN
    # The EM-018 spread plan was refreshed for all horizons.
    forecasts = session.scalars(
        select(FireForecast).where(FireForecast.event_key == event.event_key)
    ).all()
    assert len(forecasts) == 3
    # Exactly one operator-facing summary entry on the live feed.
    rows = _feed_rows(session, str(event.event_key))
    assert len(rows) == 1
    entry = result["entry"]
    assert entry["kind"] == "forecast"
    assert entry["source"] == RECOMPUTE_SOURCE
    assert entry["title"].startswith("Plan güncellendi")
    assert "Değişen" in entry["message"]
    assert entry["payload"]["plan_update"] is True
    assert "state" in entry["payload"]


def test_recompute_then_stable_within_window_is_debounced(session):
    event = _event(session)
    _resource(session, "AR-C1")
    run_recompute(session, _Settings(), event)
    decision = evaluate_recompute(session, _Settings(), event, now=utc_now())
    assert decision["should_recompute"] is False
    assert decision["reason"] == REASON_DEBOUNCING


def test_recompute_stable_once_debounce_passes(session):
    event = _event(session)
    _resource(session, "AR-C1")
    baseline = utc_now()
    run_recompute(session, _Settings(), event, now=baseline)
    later = baseline + timedelta(minutes=_Settings.SPREAD_TRIGGER_DEBOUNCE_MINUTES + 5)
    decision = evaluate_recompute(session, _Settings(), event, now=later)
    assert decision["should_recompute"] is False
    assert decision["reason"] == REASON_STABLE


def test_capacity_change_triggers_recompute_after_debounce(session):
    event = _event(session)
    _resource(session, "AR-C1")  # baseline capacity 2.0 ha/h
    baseline = utc_now()
    run_recompute(session, _Settings(), event, now=baseline)
    _resource(session, "AR-C2")  # doubles capacity -> 4.0 (+100% >= 10%)
    later = baseline + timedelta(minutes=_Settings.SPREAD_TRIGGER_DEBOUNCE_MINUTES + 5)
    decision = evaluate_recompute(session, _Settings(), event, now=later)
    assert decision["should_recompute"] is True
    assert decision["reason"] == REASON_CHANGED
    assert "capacity" in decision["changed"]


def test_position_change_triggers_recompute_after_debounce(session):
    event = _event(session, lat=38.9, lon=27.5)
    _resource(session, "AR-C1")
    baseline = utc_now()
    run_recompute(session, _Settings(), event, now=baseline)
    event.latitude = 38.95  # ~5.5 km north, past the 1 km floor
    session.commit()
    later = baseline + timedelta(minutes=_Settings.SPREAD_TRIGGER_DEBOUNCE_MINUTES + 5)
    decision = evaluate_recompute(session, _Settings(), event, now=later)
    assert decision["should_recompute"] is True
    assert "position" in decision["changed"]


def test_sweep_disabled_skips_everything(session):
    class _Disabled(_Settings):
        AUTO_RECOMPUTE_ENABLED = False

    _event(session, key="evt-ar-off")
    summary = auto_recompute_sweep(session, _Disabled())
    assert summary["enabled"] is False
    assert summary["recomputed_count"] == 0
    assert summary["checked"] == 1


def test_sweep_recomputes_new_active_events(session):
    _event(session, key="evt-ar-a")
    _event(session, key="evt-ar-b")
    _resource(session, "AR-C1")
    summary = auto_recompute_sweep(session, _Settings())
    assert summary["recomputed_count"] == 2
    keys = {row["event_key"] for row in summary["recomputed"]}
    assert keys == {"evt-ar-a", "evt-ar-b"}


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


def test_recompute_status_endpoint_reports_new_plan(client, session):
    _event(session, key="evt-ar-api")
    resp = client.get(
        "/api/v1/spread/recompute-status", params={"event_key": "evt-ar-api"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["should_recompute"] is True
    assert body["reason"] == REASON_NEW_PLAN
    assert body["auto_recompute_enabled"] is True


def test_recompute_status_endpoint_missing_event_404(client):
    resp = client.get("/api/v1/spread/recompute-status", params={"event_key": "nope"})
    assert resp.status_code == 404


def test_recompute_sweep_endpoint_runs_and_records(client, session):
    _event(session, key="evt-ar-sweep")
    _resource(session, "AR-C1")
    resp = client.post(
        "/api/v1/spread/recompute-sweep", params={"event_key": "evt-ar-sweep"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["recomputed_count"] == 1
    # The sweep committed a live-feed entry to the shared test database.
    assert len(_feed_rows(session, "evt-ar-sweep")) == 1
