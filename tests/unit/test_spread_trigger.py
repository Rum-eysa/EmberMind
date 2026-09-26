"""Unit tests for EM-018: automatic spread-forecast triggering with debounce."""
from datetime import timedelta

from sqlalchemy import select

from src.models.spatial import FireEvent, FireForecast
from src.models.weather import WeatherDataPoint
from src.services.spread_trigger import (
    REASON_DEBOUNCING,
    REASON_INPUTS_CHANGED,
    REASON_NEW_EVENT,
    REASON_STABLE,
    auto_trigger_forecasts,
    evaluate_trigger,
    inputs_changed_meaningfully,
    run_spread_forecast,
)
from src.utils.timeutils import utc_now


class TriggerSettings:
    """Settings stub for the auto-trigger service and spread engine."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False

    SPREAD_AUTO_TRIGGER_ENABLED = True
    SPREAD_TRIGGER_INTERVAL_MINUTES = 10
    SPREAD_TRIGGER_DEBOUNCE_MINUTES = 15.0
    SPREAD_TRIGGER_WIND_SPEED_KMH_THRESHOLD = 10.0
    SPREAD_TRIGGER_WIND_DIR_DEG_THRESHOLD = 30.0
    SPREAD_TRIGGER_HUMIDITY_PCT_THRESHOLD = 10.0
    SPREAD_TRIGGER_TEMP_C_THRESHOLD = 5.0


def _seed_event(session, key="evt-1", status="active", lat=38.9, lon=27.5):
    """Persist a fire event and return it."""
    event = FireEvent(
        event_key=key,
        name="EM-018 Event",
        latitude=lat,
        longitude=lon,
        min_lat=lat - 0.05,
        max_lat=lat + 0.05,
        min_lon=lon - 0.05,
        max_lon=lon + 0.05,
        geometry_wkt="",
        severity="high",
        status=status,
        started_at=utc_now(),
        source="test",
    )
    session.add(event)
    session.commit()
    return event


def _forecast_count(session, key):
    return len(
        session.scalars(select(FireForecast).where(FireForecast.event_key == key)).all()
    )


# ---------------------------------------------------------------------------
# Pure change-detection logic
# ---------------------------------------------------------------------------


def test_no_change_when_inputs_identical():
    prev = {
        "wind_speed_kmh": 20,
        "wind_from_deg": 90,
        "relative_humidity_pct": 30,
        "air_temp_c": 28,
    }
    assert inputs_changed_meaningfully(prev, dict(prev), TriggerSettings()) is False


def test_wind_speed_change_beyond_threshold_triggers():
    prev = {
        "wind_speed_kmh": 10,
        "wind_from_deg": 90,
        "relative_humidity_pct": 30,
        "air_temp_c": 28,
    }
    cur = {
        "wind_speed_kmh": 25,
        "wind_from_deg": 90,
        "relative_humidity_pct": 30,
        "air_temp_c": 28,
    }
    assert inputs_changed_meaningfully(prev, cur, TriggerSettings()) is True


def test_wind_direction_uses_wraparound_difference():
    # 350 -> 10 is a 20-degree move (below the 30-degree threshold).
    prev = {
        "wind_speed_kmh": 10,
        "wind_from_deg": 350,
        "relative_humidity_pct": 30,
        "air_temp_c": 28,
    }
    cur = {
        "wind_speed_kmh": 10,
        "wind_from_deg": 10,
        "relative_humidity_pct": 30,
        "air_temp_c": 28,
    }
    assert inputs_changed_meaningfully(prev, cur, TriggerSettings()) is False
    # 0 -> 180 is a genuine reversal.
    cur["wind_from_deg"] = 180
    assert inputs_changed_meaningfully(prev, cur, TriggerSettings()) is True


def test_humidity_and_temperature_thresholds():
    prev = {
        "wind_speed_kmh": 10,
        "wind_from_deg": 90,
        "relative_humidity_pct": 30,
        "air_temp_c": 28,
    }
    hum = dict(prev, relative_humidity_pct=45)
    temp = dict(prev, air_temp_c=36)
    assert inputs_changed_meaningfully(prev, hum, TriggerSettings()) is True
    assert inputs_changed_meaningfully(prev, temp, TriggerSettings()) is True


# ---------------------------------------------------------------------------
# Trigger decision
# ---------------------------------------------------------------------------


def test_new_event_without_forecast_triggers(session):
    event = _seed_event(session)
    decision = evaluate_trigger(session, TriggerSettings(), event)
    assert decision["should_run"] is True
    assert decision["reason"] == REASON_NEW_EVENT


def test_recent_forecast_is_debounced(session):
    event = _seed_event(session)
    run_spread_forecast(session, TriggerSettings(), event)
    decision = evaluate_trigger(session, TriggerSettings(), event)
    assert decision["should_run"] is False
    assert decision["reason"] == REASON_DEBOUNCING


def test_stable_inputs_after_debounce_window(session):
    event = _seed_event(session)
    run_spread_forecast(session, TriggerSettings(), event)
    future = utc_now() + timedelta(
        minutes=TriggerSettings.SPREAD_TRIGGER_DEBOUNCE_MINUTES + 5
    )
    decision = evaluate_trigger(session, TriggerSettings(), event, now=future)
    assert decision["should_run"] is False
    assert decision["reason"] == REASON_STABLE


def test_meaningful_input_change_after_debounce_retriggers(session):
    event = _seed_event(session)
    run_spread_forecast(session, TriggerSettings(), event)
    # A strong new wind observation shifts the resolved inputs.
    now = utc_now()
    session.add(
        WeatherDataPoint(
            cluster_key="gust",
            latitude=event.latitude,
            longitude=event.longitude,
            temperature=35.0,
            humidity=15.0,
            wind_speed=20.0,  # m/s -> ~72 km/h, far past the 10 km/h threshold
            wind_deg=45.0,
            rain=0.0,
            forecast_offset_hours=0,
            forecast_time=now,
            fetched_at=now,
        )
    )
    session.commit()
    future = now + timedelta(
        minutes=TriggerSettings.SPREAD_TRIGGER_DEBOUNCE_MINUTES + 5
    )
    decision = evaluate_trigger(session, TriggerSettings(), event, now=future)
    assert decision["should_run"] is True
    assert decision["reason"] == REASON_INPUTS_CHANGED


# ---------------------------------------------------------------------------
# Forecast run + sweep
# ---------------------------------------------------------------------------


def test_run_spread_forecast_persists_all_horizons(session):
    event = _seed_event(session)
    summary = run_spread_forecast(session, TriggerSettings(), event)
    assert summary["model_name"] == "rothermel_v1"
    assert summary["forecast_count"] == 3
    assert summary["horizons"] == [30, 60, 120]
    assert _forecast_count(session, "evt-1") == 3


def test_auto_trigger_sweep_runs_new_and_debounces_repeat(session):
    _seed_event(session, key="sweep-a")
    _seed_event(session, key="sweep-b")

    first = auto_trigger_forecasts(session, TriggerSettings())
    assert first["checked"] == 2
    assert first["triggered_count"] == 2
    assert _forecast_count(session, "sweep-a") == 3

    # Immediately running again must not re-forecast (debounce).
    second = auto_trigger_forecasts(session, TriggerSettings())
    assert second["triggered_count"] == 0
    assert second["skipped"][REASON_DEBOUNCING] == 2
    assert _forecast_count(session, "sweep-a") == 3


def test_auto_trigger_ignores_non_active_events(session):
    _seed_event(session, key="done", status="extinguished")
    result = auto_trigger_forecasts(session, TriggerSettings())
    assert result["checked"] == 0
    assert _forecast_count(session, "done") == 0


def test_auto_trigger_event_key_filter(session):
    _seed_event(session, key="keep")
    _seed_event(session, key="skip")
    result = auto_trigger_forecasts(session, TriggerSettings(), event_keys=["keep"])
    assert result["checked"] == 1
    assert result["triggered_count"] == 1
    assert _forecast_count(session, "skip") == 0


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_trigger_status_endpoint(client, session):
    _seed_event(session, key="api-trig")
    resp = client.get("/api/v1/spread/trigger-status", params={"event_key": "api-trig"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["should_run"] is True
    assert body["reason"] == REASON_NEW_EVENT


def test_trigger_status_unknown_event_404(client):
    resp = client.get("/api/v1/spread/trigger-status", params={"event_key": "nope"})
    assert resp.status_code == 404


def test_trigger_sweep_endpoint(client, session):
    _seed_event(session, key="api-sweep")
    resp = client.post("/api/v1/spread/trigger-sweep")
    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered_count"] == 1
    assert _forecast_count(session, "api-sweep") == 3


# ---------------------------------------------------------------------------
# Celery wiring
# ---------------------------------------------------------------------------


def test_celery_task_and_beat_schedule_registered():
    """EM-018: the debounced sweep runs as a periodic Celery task."""
    from src.config.settings import ProductionConfig
    from src.tasks import celery_app

    assert "src.tasks.trigger_spread_forecasts" in celery_app.tasks
    entry = celery_app.conf.beat_schedule["trigger-spread-forecasts"]
    assert entry["task"] == "src.tasks.trigger_spread_forecasts"
    assert entry["schedule"] == ProductionConfig.SPREAD_TRIGGER_INTERVAL_MINUTES * 60
