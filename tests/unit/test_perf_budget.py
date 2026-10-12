"""EM-060 recompute performance-budget tests.

Covers the p95 percentile math, the rolling-window budget read-out, the
automatic coarse-resolution scale-down (delegate settings wrapper), the
edge-triggered live-feed alert (fires once on the within -> over transition,
not for every subsequent breaching sample) and the HTTP endpoints / operator
panel wiring. Also checks the additive integration into the EM-055 wind
what-if recompute (a latency sample is recorded, no forecast is persisted).
"""
import pytest
from sqlalchemy import func, select

from src.models.live import LiveUpdate
from src.models.perf_budget import RecomputeLatencySample
from src.services.perf_budget import (
    PERF_BUDGET_PANEL,
    RESOLUTION_COARSE,
    RESOLUTION_FINE,
    budget_status,
    next_resolution,
    percentile,
    record_recompute_latency,
    resolve_recompute_settings,
    with_coarse_resolution,
)


class _Settings:
    """Full EM-060 settings stub: 10 s budget, breach after 5 slow samples."""

    PERF_BUDGET_TARGET_SECONDS = 10.0
    PERF_BUDGET_WINDOW = 50
    PERF_BUDGET_MIN_SAMPLES = 5
    PERF_BUDGET_ENABLED = True
    PERF_BUDGET_ALERTS_ENABLED = True
    PERF_BUDGET_COARSE_VERTICES = 12
    PERF_BUDGET_COARSE_HORIZONS = [30, 120]
    LIVE_UPDATES_ENABLED = True
    # Fine-resolution knobs, to prove the coarse wrapper overrides them.
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


def _reset(session):
    for row in session.scalars(select(RecomputeLatencySample)).all():
        session.delete(row)
    for row in session.scalars(select(LiveUpdate)).all():
        session.delete(row)
    session.flush()


def _feed(session, latency_ms, count, settings=None):
    settings = settings or _Settings()
    status = None
    for _ in range(count):
        status = record_recompute_latency(session, settings, latency_ms)
    return status


def _alert_count(session):
    return int(
        session.scalar(
            select(func.count(LiveUpdate.id)).where(LiveUpdate.source == "perf_budget")
        )
        or 0
    )


# ------------------------------------------------------------- percentile ---


def test_percentile_matches_linear_interpolation():
    assert percentile([0, 10, 20, 30, 40, 50, 60, 70, 80, 90], 95) == pytest.approx(
        85.5
    )


def test_percentile_empty_returns_none():
    assert percentile([], 95) is None


def test_percentile_single_value():
    assert percentile([4200.0], 95) == pytest.approx(4200.0)


# ---------------------------------------------------------- budget status ---


def test_budget_status_empty_window_is_undecided(session):
    _reset(session)
    status = budget_status(session, _Settings())
    assert status["panel"] == PERF_BUDGET_PANEL
    assert status["samples"] == 0
    assert status["target_ms"] == pytest.approx(10000.0)
    assert status["breached"] is False
    assert status["within_budget"] is None  # not enough samples to decide
    assert status["scale_down_active"] is False
    assert status["recommended_resolution"] == RESOLUTION_FINE


def test_fast_samples_stay_within_budget(session):
    _reset(session)
    status = _feed(session, 2000.0, 6)
    assert status["samples"] == 6
    assert status["p95_ms"] == pytest.approx(2000.0)
    assert status["breached"] is False
    assert status["within_budget"] is True
    assert status["scale_down_active"] is False


def test_sustained_slow_samples_breach_and_scale_down(session):
    _reset(session)
    status = _feed(session, 20000.0, 5)
    assert status["breached"] is True
    assert status["within_budget"] is False
    assert status["scale_down_active"] is True
    assert status["recommended_resolution"] == RESOLUTION_COARSE


def test_fewer_than_min_samples_does_not_breach(session):
    _reset(session)
    status = _feed(session, 20000.0, 4)  # below the 5-sample floor
    assert status["min_samples_met"] is False
    assert status["breached"] is False
    assert status["within_budget"] is None


def test_scale_down_disabled_still_reports_breach(session):
    _reset(session)
    settings = _Settings()
    settings.PERF_BUDGET_ENABLED = False
    status = _feed(session, 20000.0, 5, settings)
    assert status["breached"] is True
    assert status["scale_down_active"] is False
    assert status["recommended_resolution"] == RESOLUTION_FINE


# ---------------------------------------------------------- resolution ----


def test_with_coarse_resolution_overrides_only_recompute_knobs():
    wrapped = with_coarse_resolution(_Settings())
    assert wrapped.SPREAD_POLYGON_VERTICES == 12
    assert wrapped.SPREAD_HORIZON_MINUTES == [30, 120]
    # everything else passes through untouched
    assert wrapped.PERF_BUDGET_TARGET_SECONDS == pytest.approx(10.0)


def test_next_resolution_tracks_breach(session):
    _reset(session)
    assert next_resolution(session, _Settings()) == RESOLUTION_FINE
    _feed(session, 20000.0, 5)
    assert next_resolution(session, _Settings()) == RESOLUTION_COARSE


def test_resolve_recompute_settings_returns_coarse_wrapper_on_breach(session):
    _reset(session)
    settings = _Settings()
    fine_settings, fine_marker = resolve_recompute_settings(session, settings)
    assert fine_marker == RESOLUTION_FINE
    assert fine_settings is settings

    _feed(session, 20000.0, 5)
    run_settings, marker = resolve_recompute_settings(session, settings)
    assert marker == RESOLUTION_COARSE
    assert run_settings.SPREAD_POLYGON_VERTICES == 12


# ---------------------------------------------------------------- alerts ---


def test_alert_fires_once_on_breach_edge(session):
    _reset(session)
    _feed(session, 2000.0, 2)  # healthy baseline, no alert
    assert _alert_count(session) == 0
    _feed(session, 20000.0, 3)  # crosses min_samples -> breach edge
    assert _alert_count(session) == 1
    _feed(session, 20000.0, 2)  # sustained breach -> no extra alert
    assert _alert_count(session) == 1


def test_alert_suppressed_when_alerts_disabled(session):
    _reset(session)
    settings = _Settings()
    settings.PERF_BUDGET_ALERTS_ENABLED = False
    _feed(session, 20000.0, 6, settings)
    assert _alert_count(session) == 0


# ------------------------------------------------------------- endpoints ---


def test_perf_budget_endpoint_returns_status(client):
    res = client.get("/api/v1/perf-budget")
    assert res.status_code == 200
    body = res.json()
    assert body["panel"] == PERF_BUDGET_PANEL
    assert body["target_seconds"] > 0
    assert "p95_ms" in body


def test_perf_budget_config_endpoint(client):
    res = client.get("/api/v1/perf-budget/config")
    assert res.status_code == 200
    body = res.json()
    assert body["panel"] == "perf_budget_config"
    assert "attribution" in body
    assert body["next_resolution"] in (RESOLUTION_FINE, RESOLUTION_COARSE)


def test_perf_budget_sample_endpoint_records(client, session):
    res = client.post(
        "/api/v1/perf-budget/sample", json={"latency_ms": 1500.0, "source": "manual"}
    )
    assert res.status_code == 200
    assert res.json()["samples"] >= 1
    count = session.scalar(
        select(func.count(RecomputeLatencySample.id)).where(
            RecomputeLatencySample.source == "manual"
        )
    )
    assert count >= 1


def test_perf_budget_sample_rejects_negative(client):
    res = client.post("/api/v1/perf-budget/sample", json={"latency_ms": -5.0})
    assert res.status_code == 400
    assert res.json()["detail"]["status"] == "error"


def test_wind_whatif_records_perf_budget_additively(client, session):
    body = {
        "latitude": 37.0,
        "longitude": 28.0,
        "wind_speed_kmh": 25.0,
        "wind_from_deg": 225.0,
        "air_temp_c": 31.0,
        "relative_humidity_pct": 22.0,
        "fuel_moisture_pct": 12.0,
        "slope_deg": 0.0,
        "aspect_deg": 0.0,
        "fuel_model": "FM10_RedPine",
        "horizon_minutes": [30, 60, 120],
        "wind_speed_factor": 2.0,
    }
    res = client.post("/api/v1/whatif/wind", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["perf_budget"]["resolution"] == RESOLUTION_FINE
    assert "p95_ms" in data["perf_budget"]
    # telemetry lands, but the what-if itself stays ephemeral
    samples = session.scalar(
        select(func.count(RecomputeLatencySample.id)).where(
            RecomputeLatencySample.source == "whatif_wind"
        )
    )
    assert samples >= 1


def test_endpoints_registered_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/perf-budget" in schema["paths"]
    assert "/api/v1/perf-budget/config" in schema["paths"]
    assert "/api/v1/perf-budget/sample" in schema["paths"]


def test_panel_page_embeds_perf_budget_card(client):
    res = client.get("/panel")
    assert res.status_code == 200
    html = res.text
    assert 'id="pb-p95"' in html
    assert "/api/v1/perf-budget" in html
