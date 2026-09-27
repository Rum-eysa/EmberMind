"""EM-019 dead fuel moisture model unit tests (1h/10h/100h classes).

Reference values were derived from the published Van Wagner / Rothermel
et al. 1986 (INT-359) equilibrium curve and the deterministic diurnal
conditioning cycle defined in src/services/fuel_moisture.py.
"""
import pytest

from src.services.fuel_moisture import (
    FuelMoistureError,
    dead_fuel_moisture,
    equilibrium_moisture_content,
)
from src.services.spread import (
    SpreadError,
    effective_dead_fuel_moisture,
    predict_spread,
    resolve_inputs,
    spread_rates,
)


class MoistureSettings:
    """Settings stub with the EM-019 model enabled."""

    FUEL_MOISTURE_MODEL_ENABLED = True
    FUEL_MOISTURE_DIURNAL_TEMP_AMPLITUDE_C = 8.0
    FUEL_MOISTURE_DIURNAL_RH_AMPLITUDE_PCT = 25.0
    FUEL_MOISTURE_CONDITIONING_HOURS = 48
    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False


class LegacyMoistureSettings(MoistureSettings):
    """Same stub with the EM-019 model switched off."""

    FUEL_MOISTURE_MODEL_ENABLED = False


# --- equilibrium curve: published reference anchors -------------------------


def test_emc_matches_published_reference_values():
    """INT-359 eq 2a anchors at T = 21.1 degC (70 degF)."""
    assert equilibrium_moisture_content(21.1, 10.0) == pytest.approx(4.50, abs=0.02)
    assert equilibrium_moisture_content(21.1, 20.0) == pytest.approx(7.21, abs=0.02)
    assert equilibrium_moisture_content(21.1, 40.0) == pytest.approx(11.56, abs=0.02)
    assert equilibrium_moisture_content(21.1, 80.0) == pytest.approx(19.95, abs=0.05)


def test_emc_monotonic_in_humidity_and_temperature():
    low_rh = equilibrium_moisture_content(30.0, 15.0)
    high_rh = equilibrium_moisture_content(30.0, 85.0)
    assert 0 < low_rh < high_rh < 40
    # Warmer air at the same RH dries the fuel slightly.
    assert equilibrium_moisture_content(35.0, 20.0) < equilibrium_moisture_content(
        15.0, 20.0
    )


# --- per-class diurnal model ------------------------------------------------


def test_class_values_match_reference_scenario():
    """Hot dry afternoon (31 degC / 22 %RH) with default conditioning."""
    result = dead_fuel_moisture(31.0, 22.0)
    assert result["observed_emc_pct"] == pytest.approx(6.05, abs=0.02)
    assert result["moisture_1h_pct"] == pytest.approx(6.19, abs=0.02)
    assert result["moisture_10h_pct"] == pytest.approx(8.80, abs=0.05)
    assert result["moisture_100h_pct"] == pytest.approx(9.35, abs=0.10)


def test_coarse_classes_are_wetter_in_the_afternoon():
    """1-h tracks the air; 10-h and 100-h retain overnight moisture."""
    result = dead_fuel_moisture(31.0, 22.0)
    assert (
        result["moisture_1h_pct"]
        < result["moisture_10h_pct"]
        < result["moisture_100h_pct"]
    )


def test_flat_forcing_converges_every_class_to_emc():
    """Zero diurnal amplitudes reproduce the pre-EM-019 EMC behaviour."""
    result = dead_fuel_moisture(21.1, 40.0, temp_amplitude_c=0.0, rh_amplitude_pct=0.0)
    for key in ("moisture_1h_pct", "moisture_10h_pct", "moisture_100h_pct"):
        assert result[key] == pytest.approx(result["observed_emc_pct"], abs=0.01)


def test_longer_conditioning_converges():
    """48 h and 168 h windows agree (start-value independence)."""
    short = dead_fuel_moisture(31.0, 22.0, conditioning_hours=48)
    long = dead_fuel_moisture(31.0, 22.0, conditioning_hours=168)
    assert short["moisture_1h_pct"] == pytest.approx(long["moisture_1h_pct"], abs=0.01)
    assert short["moisture_100h_pct"] == pytest.approx(
        long["moisture_100h_pct"], abs=0.1
    )


def test_wetter_air_wets_every_class():
    dry = dead_fuel_moisture(31.0, 22.0)
    humid = dead_fuel_moisture(31.0, 45.0)
    for key in ("moisture_1h_pct", "moisture_10h_pct", "moisture_100h_pct"):
        assert dry[key] < humid[key]


def test_model_is_deterministic():
    first = dead_fuel_moisture(28.5, 33.0)
    second = dead_fuel_moisture(28.5, 33.0)
    assert first == second


def test_invalid_inputs_raise():
    with pytest.raises(FuelMoistureError):
        dead_fuel_moisture(100.0, 20.0)
    with pytest.raises(FuelMoistureError):
        dead_fuel_moisture(20.0, 120.0)
    with pytest.raises(FuelMoistureError):
        dead_fuel_moisture(20.0, 20.0, temp_amplitude_c=-1.0)
    with pytest.raises(FuelMoistureError):
        dead_fuel_moisture(20.0, 20.0, conditioning_hours=0)


# --- effective moisture for the spread engine -------------------------------


def test_effective_moisture_weights_by_dead_loads():
    classes = dead_fuel_moisture(31.0, 22.0)
    # FM1 short grass carries only 1-h fuel -> exactly the fast class.
    assert effective_dead_fuel_moisture(1, classes) == classes["moisture_1h_pct"]
    # FM13 heavy slash is dominated by coarse classes -> much wetter.
    assert (
        effective_dead_fuel_moisture(13, classes)
        > effective_dead_fuel_moisture(4, classes)
        > effective_dead_fuel_moisture(1, classes)
    )
    assert effective_dead_fuel_moisture(13, classes) == pytest.approx(8.75, abs=0.05)
    # Every bed sits inside the class envelope.
    for number in range(1, 14):
        eff = effective_dead_fuel_moisture(number, classes)
        assert classes["moisture_1h_pct"] <= eff <= classes["moisture_100h_pct"]


def test_moisture_lowers_spread_rate():
    """Realistic damping: wetter effective moisture slows the head fire."""
    dry = spread_rates(10, 6.19, 20.0, 20.0)
    wet = spread_rates(10, 8.29, 20.0, 20.0)
    assert wet.head_m_min < dry.head_m_min
    assert wet.base_m_min < dry.base_m_min


# --- spread engine integration ----------------------------------------------


def test_resolve_inputs_uses_model_by_default(session):
    resolved = resolve_inputs(
        session,
        {
            "latitude": 30.0,
            "longitude": 20.0,
            "air_temp_c": 31.0,
            "relative_humidity_pct": 22.0,
        },
        MoistureSettings(),
    )
    inputs = resolved["inputs"]
    provenance = resolved["provenance"]
    assert provenance["fuel_moisture_pct"] == "dead_fuel_moisture_v1"
    assert inputs["fuel_moisture_1h_pct"] == pytest.approx(6.19, abs=0.02)
    assert (
        inputs["fuel_moisture_1h_pct"]
        <= inputs["fuel_moisture_pct"]
        <= inputs["fuel_moisture_100h_pct"]
    )


def test_resolve_inputs_legacy_path_when_disabled(session):
    resolved = resolve_inputs(
        session,
        {
            "latitude": 30.0,
            "longitude": 20.0,
            "air_temp_c": 31.0,
            "relative_humidity_pct": 22.0,
        },
        LegacyMoistureSettings(),
    )
    inputs = resolved["inputs"]
    assert resolved["provenance"]["fuel_moisture_pct"] == "van_wagner_emc"
    assert inputs["fuel_moisture_pct"] == pytest.approx(6.0, abs=0.1)
    assert "fuel_moisture_1h_pct" not in inputs


def test_resolve_inputs_explicit_moisture_skips_model(session):
    resolved = resolve_inputs(
        session,
        {"latitude": 30.0, "longitude": 20.0, "fuel_moisture_pct": 12.0},
        MoistureSettings(),
    )
    assert resolved["provenance"]["fuel_moisture_pct"] == "request"
    assert "fuel_moisture_1h_pct" not in resolved["inputs"]


def test_predict_rates_reflect_model(session):
    """Model-on FM10 run is slower than model-off (effective 8.29 > EMC 6.05)."""
    req = {
        "latitude": 30.0,
        "longitude": 20.0,
        "air_temp_c": 31.0,
        "relative_humidity_pct": 22.0,
        "wind_speed_kmh": 20.0,
        "wind_from_deg": 315.0,
        "slope_deg": 10.0,
        "aspect_deg": 180.0,
        "fuel_model": "FM10_RedPine",
    }
    with_model = predict_spread(session, MoistureSettings(), dict(req))
    without_model = predict_spread(session, LegacyMoistureSettings(), dict(req))
    assert with_model["inputs"]["fuel_moisture_pct"] == pytest.approx(8.29, abs=0.1)
    assert (
        with_model["forecasts"][0]["rate_of_spread_m_min"]
        < without_model["forecasts"][0]["rate_of_spread_m_min"]
    )


def test_predict_bad_weather_raises_spread_error(session):
    with pytest.raises(SpreadError):
        predict_spread(
            session,
            MoistureSettings(),
            {"latitude": 30.0, "longitude": 20.0, "relative_humidity_pct": 150.0},
        )


# --- API endpoints -----------------------------------------------------------


def test_fuel_moisture_endpoint(client):
    response = client.get(
        "/api/v1/spread/fuel-moisture",
        params={
            "air_temp_c": 31.0,
            "relative_humidity_pct": 22.0,
            "fuel_model": "FM13_HeavyLoggingSlash",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "dead_fuel_moisture_v1"
    assert (
        body["moisture_1h_pct"] < body["moisture_10h_pct"] < body["moisture_100h_pct"]
    )
    assert body["fuel_model_number"] == 13
    assert body["effective_moisture_pct"] == pytest.approx(8.75, abs=0.05)


def test_fuel_moisture_endpoint_defaults_and_errors(client):
    ok = client.get(
        "/api/v1/spread/fuel-moisture",
        params={"air_temp_c": 20.0, "relative_humidity_pct": 40.0},
    )
    assert ok.status_code == 200
    assert ok.json()["fuel_model_number"] == 4  # default fuel model
    # Engine semantics: unknown labels fall back to the default model, while
    # an explicit numeric id outside the standard 13 is a client error.
    fallback = client.get(
        "/api/v1/spread/fuel-moisture",
        params={
            "air_temp_c": 20.0,
            "relative_humidity_pct": 40.0,
            "fuel_model": "FM99",
        },
    )
    assert fallback.status_code == 200
    assert fallback.json()["fuel_model_number"] == 4
    bad = client.get(
        "/api/v1/spread/fuel-moisture",
        params={
            "air_temp_c": 20.0,
            "relative_humidity_pct": 40.0,
            "fuel_model": "99",
        },
    )
    assert bad.status_code == 400
    out_of_range = client.get(
        "/api/v1/spread/fuel-moisture",
        params={"air_temp_c": 20.0, "relative_humidity_pct": 140.0},
    )
    assert out_of_range.status_code == 422


def test_predict_response_exposes_classes(client):
    response = client.post(
        "/api/v1/spread/predict",
        json={
            "latitude": 37.0,
            "longitude": 28.0,
            "air_temp_c": 31.0,
            "relative_humidity_pct": 22.0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["input_provenance"]["fuel_moisture_pct"] == "dead_fuel_moisture_v1"
    for key in (
        "fuel_moisture_1h_pct",
        "fuel_moisture_10h_pct",
        "fuel_moisture_100h_pct",
    ):
        assert key in body["inputs"]
