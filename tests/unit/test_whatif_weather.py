"""EM-061 temperature & humidity what-if tests.

The weather knobs are the EM-055 wind mechanism transposed onto air
temperature and relative humidity. The Rothermel engine reads temp / humidity
through the equilibrium (dead) fuel moisture it derives whenever the caller
does not pin ``fuel_moisture_pct``. These tests prove the three acceptance
criteria: a scenario can be run at the service and HTTP layer, the change
actually moves the spread / risk results, and a zero delta (reset) reproduces
the original exactly. The physical direction is checked too — hotter / drier
dries the fuel and speeds the spread; cooler / wetter slows it.
"""
import pytest

from src.services.whatif import WhatIfError, run_whatif


class _Settings:
    """Settings stub: pure spread path, no barriers, target of 10 s.

    ``fuel_moisture_pct`` is deliberately NOT pinned in the requests below so
    the engine re-derives it from the (possibly perturbed) weather — that is
    the only path by which a temperature / humidity delta reaches the spread.
    """

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False
    SPREAD_BARRIERS_ENABLED = False
    WHATIF_RECOMPUTE_TARGET_SECONDS = 10.0
    EXPOSURE_POPULATION_REFERENCE = 100000


# Ignition + wind are fully pinned, but temperature / humidity / fuel moisture
# are omitted: the engine falls back to a 25 degC / 40 %RH base condition, and
# a scenario delta perturbs that resolved base for the scenario side only.
BASE = {
    "latitude": 37.0,
    "longitude": 28.0,
    "wind_speed_kmh": 25.0,
    "wind_from_deg": 225.0,
    "slope_deg": 0.0,
    "aspect_deg": 0.0,
    "fuel_model": "FM10_RedPine",
    "horizon_minutes": [30, 60, 120],
}


# ------------------------------------------------------------ acceptance 3 ---


def test_zero_delta_scenario_equals_original(session):
    result = run_whatif(
        session,
        _Settings(),
        dict(BASE, temperature_delta_c=0.0, humidity_delta_pct=0.0),
    )
    assert result["scenario"]["area_ha"] == pytest.approx(result["original"]["area_ha"])
    assert result["weather"]["scenario"] == result["weather"]["original"]


def test_no_weather_knob_scenario_equals_original(session):
    result = run_whatif(session, _Settings(), dict(BASE))
    assert result["scenario"]["area_ha"] == pytest.approx(result["original"]["area_ha"])
    assert result["weather"]["temperature_delta_c"] is None
    assert result["weather"]["humidity_delta_pct"] is None


# ------------------------------------------------------------ acceptance 2 ---


def test_hotter_drier_grows_spread_and_gap(session):
    result = run_whatif(
        session,
        _Settings(),
        dict(BASE, temperature_delta_c=15.0, humidity_delta_pct=-20.0),
    )
    weather = result["weather"]
    assert weather["scenario"]["air_temp_c"] == pytest.approx(40.0)
    assert weather["scenario"]["relative_humidity_pct"] == pytest.approx(20.0)
    # Drier fuel => faster spread => larger cumulative area and higher demand.
    assert result["scenario"]["area_ha"] > result["original"]["area_ha"]
    assert result["scenario"]["demand_ha_h"] > result["original"]["demand_ha_h"]
    # Same capacity, higher demand => the gap opens up.
    assert (
        result["capacity"]["scenario"]["gap_ha_h"]
        > result["capacity"]["original"]["gap_ha_h"]
    )


def test_cooler_wetter_shrinks_spread(session):
    result = run_whatif(
        session,
        _Settings(),
        dict(BASE, temperature_delta_c=-10.0, humidity_delta_pct=20.0),
    )
    assert result["weather"]["scenario"]["air_temp_c"] == pytest.approx(15.0)
    assert result["weather"]["scenario"]["relative_humidity_pct"] == pytest.approx(60.0)
    assert result["scenario"]["area_ha"] < result["original"]["area_ha"]


def test_humidity_only_delta_moves_area(session):
    dry = run_whatif(session, _Settings(), dict(BASE, humidity_delta_pct=-30.0))
    assert dry["scenario"]["area_ha"] > dry["original"]["area_ha"]


# ------------------------------------------------------------------ weather --


def test_weather_block_reports_both_sides(session):
    result = run_whatif(session, _Settings(), dict(BASE, temperature_delta_c=8.0))
    weather = result["weather"]
    assert weather["original"]["air_temp_c"] == pytest.approx(25.0)
    assert weather["scenario"]["air_temp_c"] == pytest.approx(33.0)
    assert weather["temperature_delta_c"] == pytest.approx(8.0)


def test_scenario_humidity_is_clamped_to_valid_range(session):
    # -55 points against a 40 %RH base would be negative; clamp to the floor.
    result = run_whatif(session, _Settings(), dict(BASE, humidity_delta_pct=-55.0))
    assert result["weather"]["scenario"]["relative_humidity_pct"] == pytest.approx(1.0)


# ---------------------------------------------------------------- validation --


@pytest.mark.parametrize(
    "req",
    [
        dict(BASE, temperature_delta_c=1000.0),  # absurd heat delta
        dict(BASE, temperature_delta_c=-1000.0),  # absurd cold delta
        dict(BASE, humidity_delta_pct=200.0),  # humidity delta out of range
    ],
)
def test_invalid_weather_deltas_raise(session, req):
    with pytest.raises(WhatIfError):
        run_whatif(session, _Settings(), req)


# ----------------------------------------------------------------- endpoint --


def _body(**extra):
    payload = {
        "latitude": 37.0,
        "longitude": 28.0,
        "wind_speed_kmh": 25.0,
        "wind_from_deg": 225.0,
        "slope_deg": 0.0,
        "aspect_deg": 0.0,
        "fuel_model": "FM10_RedPine",
        "horizon_minutes": [30, 60, 120],
    }
    payload.update(extra)
    return payload


def test_wind_endpoint_accepts_weather_deltas(client):
    res = client.post(
        "/api/v1/whatif/wind",
        json=_body(temperature_delta_c=15.0, humidity_delta_pct=-20.0),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["weather"]["scenario"]["air_temp_c"] == pytest.approx(40.0)
    assert body["scenario"]["area_ha"] > body["original"]["area_ha"]
    # EM-060 telemetry stays wired alongside the new weather knobs.
    assert "perf_budget" in body


def test_wind_endpoint_rejects_bad_humidity_delta(client):
    res = client.post("/api/v1/whatif/wind", json=_body(humidity_delta_pct=500.0))
    assert res.status_code == 400
    assert res.json()["detail"]["status"] == "error"


# ---------------------------------------------------------------------- ui ---


def test_operator_map_ui_has_weather_sliders(client):
    page = client.get("/ui")
    assert page.status_code == 200
    html = page.text
    for element_id in (
        "whatif-temp",
        "whatif-humidity",
        "whatif-temp-val",
        "whatif-humidity-val",
    ):
        assert element_id in html
