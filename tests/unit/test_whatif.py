"""EM-055 wind what-if & dynamic recompute tests.

Covers the ephemeral live recomputation (original vs scenario), the operator
wind knobs (rotation delta / speed factor and absolute overrides), the capacity
gap expressed in EM-028's ha/hour unit, the recommendation re-ranking against
the scenario polygons, the sub-target recompute budget, the no-persist contract
and the HTTP endpoints / operator-map UI wiring.
"""
import json

import pytest
from sqlalchemy import func, select

from src.models.exposure import ExposedAsset
from src.models.inventory import SuppressionResource
from src.models.spatial import FireForecast
from src.services.whatif import (
    WhatIfError,
    recompute_target_seconds,
    run_whatif,
)


class _Settings:
    """Settings stub: pure spread path, no barriers, target of 10 s."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False
    SPREAD_BARRIERS_ENABLED = False
    WHATIF_RECOMPUTE_TARGET_SECONDS = 10.0
    EXPOSURE_POPULATION_REFERENCE = 100000


# Fully pinned ignition scenario so the engine needs no stored layers.
BASE = {
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
}


def _peak(side):
    return max(side["per_horizon"], key=lambda row: row["horizon_minutes"])


# ----------------------------------------------------------------- service ---


def test_delta_zero_scenario_equals_original(session):
    result = run_whatif(session, _Settings(), dict(BASE, wind_rotation_delta_deg=0.0))
    assert result["scenario"]["area_ha"] == pytest.approx(result["original"]["area_ha"])
    assert result["capacity"]["gap_delta_ha_h"] == pytest.approx(0.0)
    assert result["persistence"] == "none"


def test_no_wind_knob_scenario_equals_original(session):
    result = run_whatif(session, _Settings(), dict(BASE))
    assert result["scenario"]["area_ha"] == pytest.approx(result["original"]["area_ha"])


def test_speed_factor_grows_area_and_gap(session):
    session.add(
        SuppressionResource(
            resource_key="HEL-GAP",
            name="Helikopter GAP",
            resource_type="helicopter",
            latitude=37.0,
            longitude=28.0,
            status="available",
            capacity=10.0,
        )
    )
    session.flush()
    result = run_whatif(session, _Settings(), dict(BASE, wind_speed_factor=2.0))
    assert result["scenario"]["area_ha"] > result["original"]["area_ha"]
    assert result["scenario"]["demand_ha_h"] > result["original"]["demand_ha_h"]
    assert result["capacity"]["gap_delta_ha_h"] > 0
    # Demand up, same capacity => coverage falls.
    assert (
        result["capacity"]["scenario"]["coverage_pct"]
        < result["capacity"]["original"]["coverage_pct"]
    )


def test_rotation_changes_spread_direction(session):
    result = run_whatif(session, _Settings(), dict(BASE, wind_rotation_delta_deg=90.0))
    assert result["wind"]["scenario"]["from_deg"] == pytest.approx(
        (result["wind"]["original"]["from_deg"] + 90.0) % 360.0
    )
    assert (
        result["scenario"]["spread_direction_deg"]
        != result["original"]["spread_direction_deg"]
    )
    assert result["scenario"]["forecasts"][0]["polygon_geojson"]["coordinates"]


def test_explicit_base_wind_flows_through(session):
    # The request's own wind is the current base condition for both sides.
    result = run_whatif(
        session,
        _Settings(),
        dict(BASE, wind_from_deg=45.0, wind_speed_kmh=60.0),
    )
    assert result["wind"]["original"]["from_deg"] == pytest.approx(45.0)
    assert result["wind"]["original"]["speed_kmh"] == pytest.approx(60.0)
    # No rotation/factor -> scenario equals the base too.
    assert result["wind"]["scenario"]["from_deg"] == pytest.approx(45.0)
    assert result["scenario"]["area_ha"] == pytest.approx(result["original"]["area_ha"])


def test_whatif_is_deterministic(session):
    req = dict(BASE, wind_rotation_delta_deg=45.0, wind_speed_factor=1.5)
    first = run_whatif(session, _Settings(), req)
    second = run_whatif(session, _Settings(), req)
    assert _peak(first["scenario"])["area_ha"] == _peak(second["scenario"])["area_ha"]
    assert [f["area_ha"] for f in first["scenario"]["forecasts"]] == [
        f["area_ha"] for f in second["scenario"]["forecasts"]
    ]


def test_recompute_within_target(session):
    result = run_whatif(session, _Settings(), dict(BASE, wind_speed_factor=2.0))
    assert result["target_seconds"] == pytest.approx(10.0)
    assert result["compute_ms"] < result["target_seconds"] * 1000.0
    assert result["within_target"] is True


def test_whatif_persists_nothing(session):
    before = session.scalar(select(func.count(FireForecast.id)))
    run_whatif(session, _Settings(), dict(BASE, wind_rotation_delta_deg=45.0))
    after = session.scalar(select(func.count(FireForecast.id)))
    assert before == after


def test_capacity_integration_reduces_gap(session):
    lean = run_whatif(session, _Settings(), dict(BASE))
    session.add(
        SuppressionResource(
            resource_key="HEL-W1",
            name="Helikopter W1",
            resource_type="helicopter",
            latitude=37.0,
            longitude=28.0,
            status="available",
            capacity=10.0,
        )
    )
    session.flush()
    stocked = run_whatif(session, _Settings(), dict(BASE))
    assert stocked["capacity"]["effective_ha_h"] > lean["capacity"]["effective_ha_h"]
    assert (
        stocked["capacity"]["scenario"]["gap_ha_h"]
        < lean["capacity"]["scenario"]["gap_ha_h"]
    )


def _seed_asset_near_ignition(session):
    lat, lon = 37.0002, 28.0002
    session.add(
        ExposedAsset(
            asset_key="VIL-W1",
            asset_type="settlement",
            name="Sinyer",
            osm_id=None,
            latitude=lat,
            longitude=lon,
            min_lat=lat,
            max_lat=lat,
            min_lon=lon,
            max_lon=lon,
            geometry_wkt=f"POINT({lon} {lat})",
            tags_json=json.dumps({"place": "village", "population": 250}),
            source="test",
        )
    )
    session.flush()


def test_recommendations_rerank_with_scenario(session):
    _seed_asset_near_ignition(session)
    result = run_whatif(session, _Settings(), dict(BASE, wind_speed_factor=2.0))
    rec = result["recommendations"]
    # Same ignition & direction, larger polygon => scenario is a superset.
    assert rec["scenario"]["count"] >= rec["original"]["count"]
    assert rec["original"]["count"] >= 1
    assert rec["delta"]["threatened_count_delta"] == (
        rec["scenario"]["count"] - rec["original"]["count"]
    )


@pytest.mark.parametrize(
    "req",
    [
        {"longitude": 28.0},  # missing latitude
        dict(BASE, wind_from_deg=400.0),  # direction out of range
        dict(BASE, wind_speed_kmh=-5.0),  # negative speed
        dict(BASE, wind_rotation_delta_deg=500.0),  # delta out of range
    ],
)
def test_invalid_inputs_raise(session, req):
    with pytest.raises(WhatIfError):
        run_whatif(session, _Settings(), req)


def test_recompute_target_falls_back_without_setting():
    class _Empty:
        pass

    assert recompute_target_seconds(_Empty()) == pytest.approx(10.0)


# ------------------------------------------------------------------ routes ---


def _body(**extra):
    payload = {
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
    }
    payload.update(extra)
    return payload


def test_config_endpoint(client):
    res = client.get("/api/v1/whatif/config")
    assert res.status_code == 200
    body = res.json()
    assert body["target_seconds"] > 0
    assert body["persistence"] == "none"


def test_wind_endpoint_happy_path(client):
    res = client.post("/api/v1/whatif/wind", json=_body(wind_rotation_delta_deg=45.0))
    assert res.status_code == 200
    body = res.json()
    assert body["original"]["area_ha"] > 0
    assert body["scenario"]["forecasts"]
    assert body["capacity"]["unit"] == "ha/saat"
    assert "recommendations" in body
    assert body["within_target"] is True


def test_wind_endpoint_rejects_bad_direction(client):
    res = client.post("/api/v1/whatif/wind", json=_body(wind_from_deg=400.0))
    assert res.status_code == 400
    assert res.json()["detail"]["status"] == "error"


def test_wind_endpoint_requires_coordinates(client):
    res = client.post("/api/v1/whatif/wind", json={"wind_speed_kmh": 30.0})
    assert res.status_code == 422


def test_endpoints_registered_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/whatif/wind" in schema["paths"]
    assert "/api/v1/whatif/config" in schema["paths"]


def test_operator_map_ui_has_whatif_controls(client):
    page = client.get("/ui")
    assert page.status_code == 200
    html = page.text
    for element_id in ("whatif-panel", "whatif-dir", "whatif-speed", "whatif-rot45"):
        assert element_id in html
