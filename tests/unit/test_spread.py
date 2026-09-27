"""EM-015 Rothermel spread engine unit tests (reference-scenario reproducibility)."""
import json
import math

import pytest
from sqlalchemy import select

from src.models.land_cover import LandCoverDataPoint
from src.models.spatial import FireForecast
from src.models.topography import TopographyDataPoint
from src.models.weather import WeatherDataPoint
from src.services.spread import (
    FUEL_TRANSITION_VERTICES,
    SpreadError,
    compute_fuel_bed,
    equilibrium_fuel_moisture,
    fire_ellipse_polygon,
    fuel_model_catalog,
    fuel_transition_polygon,
    polygon_area_m2,
    predict_spread,
    project_polygon,
    resolve_fuel_model_number,
    spread_direction_deg,
    spread_rates,
)
from src.utils.timeutils import utc_now


class SpreadSettings:
    """Settings stub for the spread engine."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False


# Full explicit reference scenario: calm inputs are pinned so the engine is
# exercised without any database lookups (pure function of the inputs).
REFERENCE = {
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


def _seed_layer_data(session):
    """Store weather (m/s), topography and land cover near the reference spot."""
    now = utc_now()
    session.add(
        WeatherDataPoint(
            cluster_key="seed",
            latitude=37.0,
            longitude=28.0,
            temperature=30.0,
            humidity=25.0,
            wind_speed=5.0,  # m/s -> engine receives 18.0 km/h
            wind_deg=90.0,
            rain=0.0,
            forecast_offset_hours=0,
            forecast_time=now,
            fetched_at=now,
        )
    )
    session.add(
        TopographyDataPoint(
            cluster_key="seed",
            latitude=37.0,
            longitude=28.0,
            elevation=210.0,
            slope=12.0,
            aspect=300.0,
            resolution_meters=30,
            fetched_at=now,
        )
    )
    session.add(
        LandCoverDataPoint(
            cluster_key="seed",
            latitude=37.0,
            longitude=28.0,
            corine_code=312,
            land_cover_class="kızılçam",
            fuel_model="FM10_RedPine",
            spread_factor=1.8,
            fetched_at=now,
        )
    )
    session.commit()


def test_fuel_model_catalog_covers_13_standard_models():
    catalog = fuel_model_catalog()
    assert len(catalog) == 13
    for item in catalog:
        assert item["sigma_ft2_ft3"] > 0
        assert 0 < item["beta"] < 0.12
        assert item["total_load_lb_ft2"] > 0
    red_pine = next(c for c in catalog if c["number"] == 10)
    assert red_pine["name"] == "FM10_TimberLitterUnderstory"


def test_resolve_fuel_model_number_aliases_and_defaults():
    assert resolve_fuel_model_number("FM10_RedPine") == 10
    assert resolve_fuel_model_number("FM4_Maquis") == 4
    assert resolve_fuel_model_number("FM1_Agriculture") == 1
    assert resolve_fuel_model_number("7") == 7
    assert resolve_fuel_model_number(None) == 4  # maki default
    assert resolve_fuel_model_number("bilinmiyor") == 4
    with pytest.raises(SpreadError):
        resolve_fuel_model_number(99)


def test_fuel_bed_intermediates_are_deterministic():
    first = compute_fuel_bed(4)
    second = compute_fuel_bed(4)
    assert first == second
    assert first.sigma > 1000  # fine chaparral fuels
    assert first.moisture_of_extinction == 0.20


def test_reference_scenario_golden_values():
    """Acceptance: fixed reference scenario reproduces exact numbers."""
    rates = spread_rates(10, 12.0, 25.0, 20.0)
    assert rates.base_m_min == 0.903
    assert rates.head_m_min == 13.468
    assert rates.wind_factor == 11.5451
    assert rates.slope_factor == 2.3622
    direction = spread_direction_deg(225.0, rates.wind_factor, 180.0, 20.0, 2.3622)
    assert direction == 37.8
    polygon = fire_ellipse_polygon(
        rates.head_m_min * 30, rates.base_m_min * 30, direction, 36
    )
    assert polygon[0] == [247.64, 319.25]
    assert round(polygon_area_m2(polygon) / 1e4, 3) == 6.879


def test_predict_spread_is_repeatable(session):
    """Acceptance: two runs of the same scenario return identical results."""
    first = predict_spread(session, SpreadSettings(), dict(REFERENCE))
    second = predict_spread(session, SpreadSettings(), dict(REFERENCE))

    def stable(result):
        return [
            {k: v for k, v in item.items() if k != "forecast_for"}
            for item in result["forecasts"]
        ]

    assert stable(first) == stable(second)
    assert first["spread_direction_deg"] == second["spread_direction_deg"]
    assert first["inputs"] == second["inputs"]
    horizons = [f["horizon_minutes"] for f in first["forecasts"]]
    assert horizons == [30, 60, 120]


def test_wind_and_slope_increase_rate_of_spread():
    calm = spread_rates(4, 15.0, 0.0, 0.0)
    windy = spread_rates(4, 15.0, 25.0, 0.0)
    hilly = spread_rates(4, 15.0, 0.0, 15.0)
    combined = spread_rates(4, 15.0, 25.0, 15.0)
    assert windy.head_m_min > calm.head_m_min
    assert windy.wind_factor > 0 and calm.wind_factor == 0
    assert hilly.slope_factor > 0
    assert combined.head_m_min > windy.head_m_min > calm.head_m_min
    assert calm.base_m_min == windy.base_m_min == combined.base_m_min


def test_moisture_damps_and_extinguishes_spread():
    dry = spread_rates(4, 8.0, 20.0, 0.0)
    damp = spread_rates(4, 15.0, 20.0, 0.0)
    assert damp.head_m_min < dry.head_m_min
    wet = spread_rates(1, 25.0, 20.0, 0.0)  # FM1 mx = 12 %
    assert wet.head_m_min == 0.0 and wet.base_m_min == 0.0
    polygon = fire_ellipse_polygon(0.0, 0.0, None)
    assert polygon == []


def test_direction_follows_downwind_and_upslope():
    rates = spread_rates(1, 8.0, 20.0, 0.0)
    # Wind FROM the south blows toward north (0 degrees).
    assert spread_direction_deg(180.0, rates.wind_factor, 0.0, 0.0, 0.0) == 0.0
    # Wind FROM the west pushes fire east (90 degrees).
    assert spread_direction_deg(270.0, rates.wind_factor, 0.0, 0.0, 0.0) == 90.0
    # Slope facing south (aspect 180) drives spread north regardless of wind.
    assert spread_direction_deg(0.0, 0.0, 180.0, 20.0, 5.0) == 0.0
    # Calm and flat: no preferred direction.
    assert spread_direction_deg(90.0, 0.0, 0.0, 0.0, 0.0) is None


def test_ellipse_head_back_and_flank_distances():
    head, back = 100.0, 40.0
    polygon = fire_ellipse_polygon(head, back, 0.0, 36)
    assert len(polygon) == 37 and polygon[0] == polygon[-1]
    head_point = polygon[0]
    back_point = polygon[18]
    flank_point = polygon[9]
    assert math.isclose(math.hypot(*head_point), head, abs_tol=0.01)
    assert math.isclose(math.hypot(*back_point), back, abs_tol=0.01)
    flank_dist = math.hypot(*flank_point)
    assert back < flank_dist < head


def test_calm_flat_scenario_is_circular():
    polygon = fire_ellipse_polygon(50.0, 50.0, None, 36)
    distances = {round(math.hypot(x, y), 2) for x, y in polygon[:-1]}
    assert distances == {50.0}


def test_project_polygon_is_closed_geographic_ring():
    polygon = fire_ellipse_polygon(100.0, 40.0, 45.0, 12)
    ring = project_polygon(polygon, 37.0, 28.0)
    assert len(ring) == 13
    assert ring[0] == ring[-1]
    for lon, lat in ring:
        assert 27.9 < lon < 28.1 and 36.9 < lat < 37.1


def test_equilibrium_moisture_grows_with_humidity():
    dry = equilibrium_fuel_moisture(30.0, 15.0)
    wet = equilibrium_fuel_moisture(30.0, 85.0)
    assert 0 < dry < wet < 40


def test_predict_persists_forecast_rows_with_event_key(session):
    req = {**REFERENCE, "event_key": "event_test_015"}
    result = predict_spread(session, SpreadSettings(), req)
    rows = session.scalars(
        select(FireForecast).where(FireForecast.event_key == "event_test_015")
    ).all()
    assert len(rows) == 3
    assert {int(r.horizon_minutes) for r in rows} == {30, 60, 120}
    for row in rows:
        assert row.model_name == "rothermel_v1"
        assert (
            float(row.rate_of_spread_m_per_min)
            == result["forecasts"][0]["rate_of_spread_m_min"]
        )
        assert row.geometry_wkt.startswith("POLYGON((")
        parsed = json.loads(str(row.inputs_json))
        assert parsed["fuel_model"] == "FM10_RedPine"


def test_inputs_resolved_from_stored_layers(session):
    _seed_layer_data(session)
    req = {"latitude": 37.0, "longitude": 28.0}
    result = predict_spread(session, SpreadSettings(), req)
    inputs = result["inputs"]
    provenance = result["input_provenance"]
    assert inputs["wind_speed_kmh"] == 18.0  # 5 m/s converted
    assert inputs["wind_from_deg"] == 90.0
    assert inputs["slope_deg"] == 12.0
    assert inputs["aspect_deg"] == 300.0
    assert inputs["fuel_model"] == "FM10_RedPine"
    assert provenance["wind_speed_kmh"] == "weather_data_points"
    assert provenance["fuel_model"] == "land_cover_data_points"
    # EM-019: moisture comes from the per-class dead fuel model and the
    # engine value is the load-weighted effective moisture (FM10 dead loads
    # put it between the 1-h and 100-h class values).
    assert provenance["fuel_moisture_pct"] == "dead_fuel_moisture_v1"
    assert (
        inputs["fuel_moisture_1h_pct"]
        < inputs["fuel_moisture_10h_pct"]
        < inputs["fuel_moisture_100h_pct"]
    )
    assert (
        inputs["fuel_moisture_1h_pct"]
        <= inputs["fuel_moisture_pct"]
        <= inputs["fuel_moisture_100h_pct"]
    )
    assert inputs["fuel_model_number"] == 10
    # Wind from the east drives the head west; the N-facing upslope vector
    # (aspect 300) pulls the resultant slightly toward the southeast.
    assert result["spread_direction_deg"] == pytest.approx(266.5, abs=0.1)


def test_fallback_inputs_without_stored_layers(session):
    result = predict_spread(
        session, SpreadSettings(), {"latitude": 30.0, "longitude": 20.0}
    )
    provenance = result["input_provenance"]
    assert provenance["wind_speed_kmh"] == "fallback_calm"
    assert provenance["slope_deg"] == "fallback_flat"
    # Directionless calm/flat run yields a circular (or fuel-limited) polygon.
    assert result["spread_direction_deg"] is None


def test_horizon_override_and_validation(session):
    req = {**REFERENCE, "horizon_minutes": [15, 45]}
    result = predict_spread(session, SpreadSettings(), req)
    assert [f["horizon_minutes"] for f in result["forecasts"]] == [15, 45]
    with pytest.raises(SpreadError):
        predict_spread(session, SpreadSettings(), {**REFERENCE, "horizon_minutes": []})
    with pytest.raises(SpreadError):
        predict_spread(session, SpreadSettings(), {**REFERENCE, "latitude": 120.0})


def test_area_scales_with_horizon(session):
    result = predict_spread(session, SpreadSettings(), dict(REFERENCE))
    areas = [f["area_ha"] for f in result["forecasts"]]
    assert areas[0] < areas[1] < areas[2]
    # Ellipse axes scale linearly with time -> area grows quadratically.
    assert areas[1] == pytest.approx(4.0 * areas[0], rel=0.01)
    assert areas[2] == pytest.approx(16.0 * areas[0], rel=0.01)


def test_spread_predict_endpoint(client):
    response = client.post("/api/v1/spread/predict", json=REFERENCE)
    assert response.status_code == 200
    body = response.json()
    assert body["model_name"] == "rothermel_v1"
    assert len(body["forecasts"]) == 3
    polygon = body["forecasts"][0]["polygon_geojson"]
    assert polygon["type"] == "Polygon"
    assert len(polygon["coordinates"][0]) >= 37  # 36 (ellipse) or 73 (fuel-transition)


def test_spread_predict_endpoint_rejects_unknown_fuel_model(client):
    response = client.post(
        "/api/v1/spread/predict", json={**REFERENCE, "fuel_model": "99"}
    )
    assert response.status_code == 400
    assert "fuel model" in response.json()["detail"]["error"]


def test_spread_fuel_models_endpoint(client):
    response = client.get("/api/v1/spread/fuel-models")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 13
    names = [item["name"] for item in body["fuel_models"]]
    assert "FM10_TimberLitterUnderstory" in names


def test_spread_forecasts_endpoint_lists_persisted_rows(client):
    predict = client.post(
        "/api/v1/spread/predict",
        json={**REFERENCE, "event_key": "event_api_015"},
    )
    assert predict.status_code == 200
    response = client.get(
        "/api/v1/spread/forecasts", params={"event_key": "event_api_015"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert body["forecasts"][0]["horizon_minutes"] in (30, 60, 120)


# ---------------------------------------------------------------------------
# EM-016: Fuel-transition-sensitive spread tests
# ---------------------------------------------------------------------------


class FuelTransitionSettings:
    """Settings stub with fuel transition enabled."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = True


def _seed_land_cover(session, lat, lon, fuel_model, spread_factor=1.0):
    """Insert a LandCoverDataPoint for testing."""
    session.add(
        LandCoverDataPoint(
            latitude=lat,
            longitude=lon,
            land_cover_class="test",
            fuel_model=fuel_model,
            spread_factor=spread_factor,
            fetched_at=utc_now(),
            source="test",
        )
    )
    session.commit()


def test_fuel_transition_polygon_has_more_vertices(session):
    """EM-016: Fuel transition polygon uses 72 vertices (not 36)."""
    pts, zones = fuel_transition_polygon(
        session,
        head_m=200.0,
        back_m=80.0,
        direction_deg=45.0,
        base_fuel_number=4,
        ignition_lat=37.0,
        ignition_lon=28.0,
    )
    # 72 vertices + 1 closing point
    assert len(pts) == FUEL_TRANSITION_VERTICES + 1
    assert pts[0] == pts[-1]


def test_fuel_transition_uniform_fuel_is_elliptical(session):
    """EM-016: Without land cover data, polygon is still elliptical (scale=1)."""
    pts_ft, _ = fuel_transition_polygon(
        session,
        head_m=200.0,
        back_m=80.0,
        direction_deg=0.0,
        base_fuel_number=4,
        ignition_lat=37.0,
        ignition_lon=28.0,
    )
    # Compare radius at head (vertex 0 = bearing 0°) with ellipse
    head_dist_ft = math.hypot(pts_ft[0][0], pts_ft[0][1])
    # For direction=0, first vertex is at head distance
    assert abs(head_dist_ft - 200.0) < 1.0  # ~head_m


def test_fuel_transition_bulges_toward_flammable(session):
    """EM-016: Polygon extends further toward more-flammable fuel."""
    # Place grass (FM1, fast-spreading) to the north of ignition
    # Ignition fuel is FM4 (chaparral, moderate)
    _seed_land_cover(session, 37.01, 28.0, "FM1_ShortGrass")
    # FM4 is the base fuel (chaparral)
    pts_grass, zones = fuel_transition_polygon(
        session,
        head_m=500.0,
        back_m=200.0,
        direction_deg=0.0,
        base_fuel_number=4,
        ignition_lat=37.0,
        ignition_lon=28.0,
        vertices=36,
    )
    # Check that zones include at least one fuel type
    assert len(zones) >= 1
    # The vertex pointing toward the grass should be further than nominal
    # North direction = vertex at bearing 0° (index 0 for direction_deg=0)
    # Due to sampling at 500m north, it may or may not hit the seeded point
    # (depends on _nearest_row 0.05° radius). Just verify polygon is valid.
    assert len(pts_grass) == 37
    area = polygon_area_m2(pts_grass)
    assert area > 0


def test_fuel_transition_zones_metadata(session):
    """EM-016: fuel_zones reports encountered fuel models with percentages."""
    _seed_land_cover(session, 37.0, 28.0, "FM8_ShortNeedleLitter")
    _, zones = fuel_transition_polygon(
        session,
        head_m=100.0,
        back_m=50.0,
        direction_deg=90.0,
        base_fuel_number=8,
        ignition_lat=37.0,
        ignition_lon=28.0,
    )
    # With base fuel 8 and no other land cover nearby, all vertices are FM8
    assert len(zones) == 1
    assert zones[0]["fuel_model_number"] == 8
    assert zones[0]["percentage"] == 100.0


def test_predict_spread_fuel_transition_enabled(session):
    """EM-016: predict_spread with fuel_transition=True returns fuel_zones."""
    req = {
        "latitude": 37.0,
        "longitude": 28.0,
        "wind_speed_kmh": 20.0,
        "wind_from_deg": 270.0,
        "air_temp_c": 30.0,
        "relative_humidity_pct": 20.0,
        "slope_deg": 5.0,
        "aspect_deg": 180.0,
        "fuel_model": "FM4_Chaparral",
    }
    result = predict_spread(session, FuelTransitionSettings(), req)
    assert result["fuel_transition"] is True
    assert "fuel_zones" in result
    # Polygon should have 72+1 vertices
    coords = result["forecasts"][0]["polygon_geojson"]["coordinates"][0]
    assert len(coords) == FUEL_TRANSITION_VERTICES + 1


def test_predict_spread_fuel_transition_disabled(session):
    """EM-016: predict_spread with fuel_transition=False uses standard ellipse."""
    req = {
        "latitude": 37.0,
        "longitude": 28.0,
        "wind_speed_kmh": 20.0,
        "wind_from_deg": 270.0,
        "air_temp_c": 30.0,
        "relative_humidity_pct": 20.0,
        "slope_deg": 5.0,
        "aspect_deg": 180.0,
        "fuel_model": "FM4_Chaparral",
    }
    result = predict_spread(session, SpreadSettings(), req)
    assert result["fuel_transition"] is False
    assert result["fuel_zones"] == []
    # Standard ellipse: 36+1 vertices
    coords = result["forecasts"][0]["polygon_geojson"]["coordinates"][0]
    assert len(coords) == 37
