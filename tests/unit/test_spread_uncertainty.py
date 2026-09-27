"""EM-020 uncertainty display tests: wind-ensemble envelope per horizon,
model-confidence indicator, API endpoints and the operator map band layer."""
import json

import pytest
from sqlalchemy import select

from src.models.spatial import FireForecast
from src.services.map_layers import LAYER_KEYS, build_layer, layer_catalog
from src.services.spread import SpreadError, predict_spread
from src.services.spread_uncertainty import (
    ENSEMBLE_MODEL_NAME,
    ensemble_scenarios,
    envelope_from_inputs,
    model_confidence,
    perturbation_settings,
    uncertainty_envelope,
)
from src.utils.timeutils import utc_now

# EM-015 reference scenario: FM10, 12 % moisture, 25 km/h from 225 deg, 20 deg slope.
REFERENCE_INPUTS = {
    "latitude": 37.0,
    "longitude": 28.0,
    "fuel_model_number": 10,
    "fuel_moisture_pct": 12.0,
    "wind_speed_kmh": 25.0,
    "wind_from_deg": 225.0,
    "slope_deg": 20.0,
    "aspect_deg": 180.0,
}

REFERENCE_BODY = {
    "latitude": 37.0,
    "longitude": 28.0,
    "wind_speed_kmh": 25.0,
    "wind_from_deg": 225.0,
    "air_temp_c": 31.0,
    "relative_humidity_pct": 22.0,
    "fuel_moisture_pct": 12.0,
    "slope_deg": 20.0,
    "aspect_deg": 180.0,
    "fuel_model": "FM10_RedPine",
}

# 60-minute reference values of the +/-10 deg / +/-15 % wind ensemble,
# produced by this engine version (regression anchors, metres / hectares).
REFERENCE_60MIN = {
    "optimistic_head_m": 678.2,
    "expected_head_m": 808.1,
    "pessimistic_head_m": 946.6,
    "optimistic_area_ha": 15.112,
    "expected_area_ha": 27.518,
    "pessimistic_area_ha": 48.162,
}


class UncertaintySettings:
    """Settings stub: ellipse polygons, default horizons, +/-10 deg / +/-15 %."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False
    SPREAD_UNCERTAINTY_WIND_DIR_DELTA_DEG = 10.0
    SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION = 0.15


def _band_60(settings=None, inputs=None):
    envelope = envelope_from_inputs(
        None, settings or UncertaintySettings(), inputs or REFERENCE_INPUTS, [60]
    )
    return envelope["horizons"][0]


# --- ensemble scenarios -----------------------------------------------------


def test_ensemble_scenarios_grid_is_symmetric_and_deterministic():
    scenarios = ensemble_scenarios(10.0, 0.15)
    assert len(scenarios) == 9
    assert {s["wind_dir_delta_deg"] for s in scenarios} == {-10.0, 0.0, 10.0}
    assert {s["wind_speed_factor"] for s in scenarios} == {0.85, 1.0, 1.15}
    expected = [
        s
        for s in scenarios
        if s["wind_dir_delta_deg"] == 0.0 and s["wind_speed_factor"] == 1.0
    ]
    assert len(expected) == 1
    assert scenarios == ensemble_scenarios(10.0, 0.15)


def test_perturbation_settings_read_and_validate():
    assert perturbation_settings(UncertaintySettings()) == (10.0, 0.15)

    class Custom(UncertaintySettings):
        SPREAD_UNCERTAINTY_WIND_DIR_DELTA_DEG = 20.0
        SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION = 0.25

    assert perturbation_settings(Custom()) == (20.0, 0.25)

    class Broken(UncertaintySettings):
        SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION = 1.5

    with pytest.raises(SpreadError, match="perturbation"):
        perturbation_settings(Broken())


# --- envelope reference values ----------------------------------------------


def test_envelope_matches_reference_values_at_60_minutes():
    band = _band_60()
    assert band["horizon_minutes"] == 60
    assert band["optimistic"]["head_distance_m"] == REFERENCE_60MIN["optimistic_head_m"]
    assert band["expected"]["head_distance_m"] == REFERENCE_60MIN["expected_head_m"]
    assert (
        band["pessimistic"]["head_distance_m"] == REFERENCE_60MIN["pessimistic_head_m"]
    )
    assert band["optimistic"]["area_ha"] == REFERENCE_60MIN["optimistic_area_ha"]
    assert band["expected"]["area_ha"] == REFERENCE_60MIN["expected_area_ha"]
    assert band["pessimistic"]["area_ha"] == REFERENCE_60MIN["pessimistic_area_ha"]
    assert band["band_width_m"] == pytest.approx(
        REFERENCE_60MIN["pessimistic_head_m"] - REFERENCE_60MIN["optimistic_head_m"],
        abs=0.1,
    )


def test_envelope_orders_optimistic_expected_pessimistic():
    band = _band_60()
    assert (
        band["optimistic"]["rate_of_spread_m_min"]
        < band["expected"]["rate_of_spread_m_min"]
        < band["pessimistic"]["rate_of_spread_m_min"]
    )
    assert (
        band["optimistic"]["area_ha"]
        < band["expected"]["area_ha"]
        < band["pessimistic"]["area_ha"]
    )
    # Backing fire is wind-speed independent here: identical on all members.
    assert (
        band["optimistic"]["back_distance_m"] == band["pessimistic"]["back_distance_m"]
    )
    assert band["pessimistic"]["scenario"]["wind_speed_factor"] == 1.15
    assert band["optimistic"]["scenario"]["wind_speed_factor"] == 0.85


def test_envelope_rings_are_closed_and_pessimistic_wraps_expected():
    band = _band_60()
    pess = band["pessimistic"]["polygon_geojson"]["coordinates"][0]
    exp = band["expected"]["polygon_geojson"]["coordinates"][0]
    assert len(pess) == UncertaintySettings.SPREAD_POLYGON_VERTICES + 1
    assert pess[0] == pess[-1]
    assert max(p[0] for p in pess) >= max(p[0] for p in exp)
    assert min(p[0] for p in pess) <= min(p[0] for p in exp)


def test_envelope_is_deterministic():
    first = envelope_from_inputs(
        None, UncertaintySettings(), REFERENCE_INPUTS, [30, 60, 120]
    )
    second = envelope_from_inputs(
        None, UncertaintySettings(), REFERENCE_INPUTS, [30, 60, 120]
    )
    for horizons in (first["horizons"], second["horizons"]):
        for band in horizons:
            band.pop("forecast_for")
    assert first == second


def test_calm_flat_fire_has_zero_band_width():
    inputs = {**REFERENCE_INPUTS, "wind_speed_kmh": 0.0, "slope_deg": 0.0}
    band = _band_60(inputs=inputs)
    assert band["band_width_m"] == pytest.approx(0.0, abs=0.1)
    assert band["optimistic"]["area_ha"] == pytest.approx(
        band["pessimistic"]["area_ha"]
    )


def test_zero_wind_direction_still_widens_the_band_spatially():
    # Calm speed: the +/-10 deg runs cannot change ROS but the heading of the
    # expected ellipse stays undefined; envelope must remain valid geometry.
    inputs = {**REFERENCE_INPUTS, "wind_speed_kmh": 0.0}
    band = _band_60(inputs=inputs)
    assert band["pessimistic"]["area_ha"] >= band["expected"]["area_ha"] > 0


# --- model confidence --------------------------------------------------------


def test_confidence_full_request_inputs_is_high():
    provenance = {
        "wind_speed_kmh": "request",
        "wind_from_deg": "request",
        "air_temp_c": "request",
        "relative_humidity_pct": "request",
        "slope_deg": "request",
        "aspect_deg": "request",
        "fuel_model": "request",
        "fuel_moisture_pct": "request",
    }
    confidence = model_confidence(provenance)
    assert confidence["score"] == 1.0
    assert confidence["band"] == "high"
    assert confidence["label"] == "Yüksek"


def test_confidence_model_derived_moisture_is_still_high():
    confidence = model_confidence(
        {"wind_speed_kmh": "request", "fuel_moisture_pct": "dead_fuel_moisture_v1"}
    )
    assert confidence["score"] == 0.85
    assert confidence["band"] == "high"


def test_confidence_fallback_heavy_inputs_are_low():
    confidence = model_confidence(
        {
            "wind_speed_kmh": "fallback_calm",
            "slope_deg": "fallback_flat",
            "fuel_model": "corine_synthetic",
            "fuel_moisture_pct": "dead_fuel_moisture_v1",
        }
    )
    assert confidence["score"] == 0.42
    assert confidence["band"] == "low"
    assert confidence["label"] == "Düşük"


def test_confidence_observed_layers_are_moderate():
    confidence = model_confidence(
        {
            "wind_speed_kmh": "weather_data_points",
            "slope_deg": "topography_data_points",
            "fuel_model": "corine_synthetic",
            "fuel_moisture_pct": "van_wagner_emc",
        }
    )
    assert confidence["band"] == "moderate"


def test_confidence_unknown_without_provenance():
    for empty in (None, {}):
        confidence = model_confidence(empty)
        assert confidence["score"] is None
        assert confidence["band"] == "unknown"
        assert confidence["label"] == "Bilinmiyor"


# --- uncertainty_envelope (input resolution) ---------------------------------


def test_uncertainty_envelope_from_request_inputs(session):
    result = uncertainty_envelope(session, UncertaintySettings(), REFERENCE_BODY)
    assert result["model"] == ENSEMBLE_MODEL_NAME
    assert result["perturbation"]["runs"] == 9
    assert [h["horizon_minutes"] for h in result["horizons"]] == [30, 60, 120]
    assert result["model_confidence"]["band"] == "high"
    assert result["input_provenance"]["fuel_moisture_pct"] == "request"
    band60 = next(h for h in result["horizons"] if h["horizon_minutes"] == 60)
    assert (
        band60["pessimistic"]["head_distance_m"]
        == REFERENCE_60MIN["pessimistic_head_m"]
    )


def test_uncertainty_envelope_fallback_inputs_lower_confidence(session):
    result = uncertainty_envelope(
        session, UncertaintySettings(), {"latitude": 37.0, "longitude": 28.0}
    )
    assert result["model_confidence"]["band"] == "low"
    assert result["input_provenance"]["wind_speed_kmh"].startswith("fallback")


def test_uncertainty_envelope_validates_coordinates(session):
    with pytest.raises(SpreadError, match="latitude and longitude"):
        uncertainty_envelope(session, UncertaintySettings(), {})
    with pytest.raises(SpreadError, match="out of range"):
        uncertainty_envelope(
            session, UncertaintySettings(), {"latitude": 95.0, "longitude": 0.0}
        )


# --- REST endpoints -----------------------------------------------------------


def test_uncertainty_endpoint_reference_envelope(client):
    response = client.post("/api/v1/spread/uncertainty", json=REFERENCE_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == ENSEMBLE_MODEL_NAME
    assert body["model_confidence"]["band"] == "high"
    band60 = next(h for h in body["horizons"] if h["horizon_minutes"] == 60)
    assert (
        band60["optimistic"]["head_distance_m"] == REFERENCE_60MIN["optimistic_head_m"]
    )
    assert (
        band60["pessimistic"]["head_distance_m"]
        == REFERENCE_60MIN["pessimistic_head_m"]
    )
    for band in body["horizons"]:
        assert band["optimistic"]["area_ha"] < band["pessimistic"]["area_ha"]


def test_uncertainty_endpoint_bad_coordinate(client):
    body = dict(REFERENCE_BODY, latitude=120.0)
    response = client.post("/api/v1/spread/uncertainty", json=body)
    assert response.status_code == 400
    assert "out of range" in response.json()["detail"]["error"]


# --- operator map layer and UI -------------------------------------------------


def test_predict_persists_provenance_for_confidence(session):
    predict_spread(
        session, UncertaintySettings(), {**REFERENCE_BODY, "event_key": "EVT-020"}
    )
    stored = json.loads(
        str(
            session.scalars(select(FireForecast).filter_by(event_key="EVT-020"))
            .first()
            .inputs_json
        )
    )
    assert stored["provenance"]["fuel_moisture_pct"] == "request"
    assert stored["wind_speed_kmh"] == 25.0


def test_uncertainty_layer_bands_and_confidence(session):
    predict_spread(
        session, UncertaintySettings(), {**REFERENCE_BODY, "event_key": "EVT-020"}
    )
    layer = build_layer(session, UncertaintySettings(), "uncertainty")
    assert layer["type"] == "FeatureCollection"
    assert layer["model_confidence"]["band"] == "high"
    assert layer["perturbation"]["model"] == ENSEMBLE_MODEL_NAME
    assert "EM-020" in layer["attribution"]
    bands = {
        (f["properties"]["horizon_minutes"], f["properties"]["band"])
        for f in layer["features"]
    }
    assert bands == {
        (h, b) for h in (30, 60, 120) for b in ("optimistic", "pessimistic")
    }
    pess_60 = next(
        f
        for f in layer["features"]
        if f["properties"]["horizon_minutes"] == 60
        and f["properties"]["band"] == "pessimistic"
    )
    assert (
        pess_60["properties"]["head_distance_m"]
        == REFERENCE_60MIN["pessimistic_head_m"]
    )
    assert pess_60["geometry"]["type"] == "Polygon"


def test_uncertainty_layer_skips_rows_without_inputs(session):
    session.add(
        FireForecast(
            event_key="EVT-Eski",
            model_name="rothermel_v1",
            latitude=37.0,
            longitude=28.0,
            predicted_area_ha=1.0,
            geometry_wkt="POLYGON(EMPTY)",
            forecast_for=utc_now(),
            horizon_minutes=30,
            rate_of_spread_m_per_min=1.0,
            spread_direction_deg=0.0,
            inputs_json="",
        )
    )
    session.commit()
    layer = build_layer(session, UncertaintySettings(), "uncertainty")
    assert layer["features"] == []
    assert layer["model_confidence"]["band"] == "unknown"


def test_uncertainty_in_layer_catalog_and_endpoint(client):
    assert "uncertainty" in LAYER_KEYS
    catalog = layer_catalog()
    assert len(catalog) == 8
    meta = next(item for item in catalog if item["key"] == "uncertainty")
    assert meta["geometry"] == "Polygon"
    assert meta["title"] == "Belirsizlik Bandı"
    response = client.get("/api/v1/map/layers/uncertainty")
    assert response.status_code == 200
    assert response.json()["layer"] == "uncertainty"


def test_ui_shows_confidence_band_and_badge(client):
    html = client.get("/ui").text
    assert 'id="confidence-badge"' in html
    assert "renderConfidence" in html
    assert "Belirsizlik bandı" in html
    assert "pessimistic" in html and "uncertainty" in html
