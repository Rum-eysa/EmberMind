"""EM-021 land/sea mask and natural barrier tests.

Reference geometry: ignition at (37.0, 28.0); FM10 at 12 % moisture.
Calm/flat gives a 54.18 m circle at 60 min; the EM-015 wind reference
(25 km/h from 225 deg, 20 deg slope) gives an 808.1 m head ellipse with
27.518 ha area (anchored in test_spread.py). Sea boxes are placed with
their shoreline at an exact metric offset north of the ignition point.
"""
import math

import pytest

from src.services.barriers import (
    BarrierError,
    delete_barrier,
    list_barriers,
    mask_local_ring,
    parse_line_string,
    parse_polygon_ring,
    point_in_ring,
    register_barrier,
)
from src.services.map_layers import build_layer
from src.services.spread import predict_spread
from src.services.spread_uncertainty import envelope_from_inputs

LAT0, LON0 = 37.0, 28.0
M_PER_DEG = 111320.0

REFERENCE_INPUTS = {
    "latitude": LAT0,
    "longitude": LON0,
    "fuel_model_number": 10,
    "fuel_moisture_pct": 12.0,
    "wind_speed_kmh": 25.0,
    "wind_from_deg": 225.0,
    "slope_deg": 20.0,
    "aspect_deg": 180.0,
}

REFERENCE_BODY = {
    "latitude": LAT0,
    "longitude": LON0,
    "wind_speed_kmh": 25.0,
    "wind_from_deg": 225.0,
    "air_temp_c": 31.0,
    "relative_humidity_pct": 22.0,
    "fuel_moisture_pct": 12.0,
    "slope_deg": 20.0,
    "aspect_deg": 180.0,
    "fuel_model": "FM10_RedPine",
}


class BarrierSettings:
    """Settings stub: ellipse polygons, EM-021 mask enabled."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False
    SPREAD_BARRIERS_ENABLED = True
    FUEL_MOISTURE_MODEL_ENABLED = False


class BarriersOffSettings(BarrierSettings):
    SPREAD_BARRIERS_ENABLED = False


def _sea(shore_m: float, barrier_key: str = "SEA-1") -> dict:
    """Sea polygon whose shoreline runs east-west shore_m north of ignition."""
    shore_lat = LAT0 + shore_m / M_PER_DEG
    return {
        "barrier_key": barrier_key,
        "name": "Demo Denizi",
        "barrier_type": "sea",
        "geometry_wkt": (
            f"POLYGON(({LON0 - 0.1} {shore_lat}, {LON0 + 0.1} {shore_lat},"
            f" {LON0 + 0.1} {shore_lat + 0.1}, {LON0 - 0.1} {shore_lat + 0.1},"
            f" {LON0 - 0.1} {shore_lat}))"
        ),
    }


def _road(offset_m: float, factor: float | None = None) -> dict:
    """East-west road line offset_m north of the ignition point."""
    road_lat = LAT0 + offset_m / M_PER_DEG
    body = {
        "barrier_key": "ROAD-1",
        "name": "Sahil Yolu",
        "barrier_type": "road",
        "geometry_wkt": (
            f"LINESTRING({LON0 - 0.05} {road_lat}, {LON0 + 0.05} {road_lat})"
        ),
    }
    if factor is not None:
        body["slowdown_factor"] = factor
    return body


def _circle_ring(radius: float, vertices: int = 36) -> list[list[float]]:
    """Closed circular ring around the origin (calm-fire polygon stand-in)."""
    points = []
    for step in range(vertices):
        bearing = math.radians(360.0 * step / vertices)
        points.append(
            [
                round(radius * math.sin(bearing), 2),
                round(radius * math.cos(bearing), 2),
            ]
        )
    points.append(list(points[0]))
    return points


def _load(session, *barriers):
    for barrier in barriers:
        register_barrier(session, barrier)
    from src.services.barriers import load_active_barriers

    return load_active_barriers(session)


def _area(points) -> float:
    from src.services.spread import polygon_area_m2

    return round(polygon_area_m2(points) / 10000.0, 3)


# --- parsing and primitives ---------------------------------------------------


def test_parse_ring_and_line_valid_and_invalid():
    ring = parse_polygon_ring("POLYGON((28 37, 28.1 37, 28.1 37.1, 28 37))")
    assert ring[0] == [28.0, 37.0]
    line = parse_line_string("LINESTRING(28 37, 28.1 37.1)")
    assert len(line) == 2
    with pytest.raises(BarrierError, match="POLYGON"):
        parse_polygon_ring("LINESTRING(28 37, 28.1 37)")
    with pytest.raises(BarrierError, match="LINESTRING"):
        parse_line_string("POLYGON((28 37, 28.1 37))")
    with pytest.raises(BarrierError, match="at least"):
        parse_line_string("LINESTRING(28 37)")


def test_point_in_ring_basic():
    square = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]
    assert point_in_ring([50.0, 50.0], square)
    assert not point_in_ring([150.0, 50.0], square)


# --- full barrier (water) masking ----------------------------------------------


def test_sea_clips_ring_at_the_shoreline(session):
    barriers = _load(session, _sea(40.0))
    masked = mask_local_ring(LAT0, LON0, _circle_ring(54.18), barriers)
    # North vertex lands exactly on the shore; nothing spills into the sea.
    assert masked[0] == [0.0, 40.0]
    assert max(p[1] for p in masked) == 40.0
    # The opposite (south) vertex is untouched.
    assert masked[18] == [0.0, -54.18]
    assert _area(masked) == 0.846


def test_fire_that_never_reaches_the_water_is_unchanged(session):
    barriers = _load(session, _sea(100.0))
    ring = _circle_ring(54.18)
    assert mask_local_ring(LAT0, LON0, ring, barriers) == ring


def test_windy_ellipse_head_is_truncated_by_the_sea(session):
    from src.services.spread import (
        fire_ellipse_polygon,
        spread_direction_deg,
        spread_rates,
    )

    rates = spread_rates(10, 12.0, 25.0, 20.0)
    direction = spread_direction_deg(
        225.0, rates.wind_factor, 180.0, 20.0, rates.slope_factor
    )
    ring = fire_ellipse_polygon(
        rates.head_m_min * 60, rates.base_m_min * 60, direction, 36
    )
    barriers = _load(session, _sea(500.0))
    masked = mask_local_ring(LAT0, LON0, ring, barriers)
    assert max(p[1] for p in masked) == pytest.approx(500.0, abs=0.05)
    assert _area(masked) == 23.189  # vs 27.518 ha unmasked (EM-015 anchor)


def test_ignition_inside_water_collapses_the_polygon(session):
    barriers = _load(session, _sea(-10.0))  # shoreline south of ignition
    masked = mask_local_ring(LAT0, LON0, _circle_ring(54.18), barriers)
    assert all(p == [0.0, 0.0] for p in masked)


def test_lake_beyond_reach_does_not_affect_the_ring(session):
    lake = _sea(2000.0, barrier_key="LAKE-1")
    lake["barrier_type"] = "lake"
    barriers = _load(session, lake)
    ring = _circle_ring(54.18)
    assert mask_local_ring(LAT0, LON0, ring, barriers) == ring


# --- partial barriers (roads / streams) -----------------------------------------


def test_road_slows_crossing_rays_only(session):
    barriers = _load(session, _road(50.0))
    masked = mask_local_ring(LAT0, LON0, _circle_ring(54.18), barriers)
    # North vertex crosses the road: 54.18 * 0.6 = 32.51.
    assert masked[0] == [0.0, 32.51]
    # East vertex runs along the road line: no crossing, full reach.
    assert masked[9] == [54.18, 0.0]
    assert _area(masked) == 0.832


def test_partial_barrier_factor_is_configurable(session):
    barriers = _load(session, _road(50.0, factor=0.25))
    masked = mask_local_ring(LAT0, LON0, _circle_ring(54.18), barriers)
    # 54.18 * 0.25 = 13.545 -> the float round() lands on 13.54.
    assert masked[0] == [0.0, 13.54]


def test_sea_takes_precedence_then_road_slows_the_clipped_ray(session):
    barriers = _load(session, _sea(40.0), _road(20.0))
    masked = mask_local_ring(LAT0, LON0, _circle_ring(54.18), barriers)
    # North ray: clipped to 40 m by the sea, then slowed to 24 m by the road.
    assert masked[0] == [0.0, 24.0]


# --- registration validation -----------------------------------------------------


def test_register_barrier_defaults_and_validation(session):
    road = register_barrier(session, _road(50.0))
    assert road["slowdown_factor"] == 0.6  # type default for road
    assert road["is_active"] is True
    with pytest.raises(BarrierError, match="unknown barrier_type"):
        register_barrier(session, dict(_sea(10.0), barrier_type="kahve"))
    with pytest.raises(BarrierError, match="POLYGON"):
        register_barrier(session, dict(_sea(10.0), geometry_wkt="LINESTRING(1 2, 3 4)"))
    with pytest.raises(BarrierError, match="slowdown_factor"):
        register_barrier(session, dict(_road(50.0), slowdown_factor=1.5))
    with pytest.raises(BarrierError, match="name is required"):
        register_barrier(session, dict(_road(50.0), name="  "))
    with pytest.raises(BarrierError, match="already exists"):
        register_barrier(session, _road(50.0))


def test_list_and_delete_barriers(session):
    register_barrier(session, _sea(40.0))
    register_barrier(session, _road(50.0))
    assert {b["barrier_key"] for b in list_barriers(session)} == {"SEA-1", "ROAD-1"}
    assert delete_barrier(session, "SEA-1") is True
    assert delete_barrier(session, "SEA-1") is False
    assert len(list_barriers(session)) == 1


# --- engine integration -----------------------------------------------------------


def test_predict_spread_area_respects_the_sea_mask(session):
    plain = predict_spread(session, BarrierSettings(), REFERENCE_BODY)
    baseline_60 = next(f for f in plain["forecasts"] if f["horizon_minutes"] == 60)[
        "area_ha"
    ]
    assert baseline_60 == 27.518  # EM-015 anchor: no barriers registered yet
    register_barrier(session, _sea(500.0))
    clipped = predict_spread(session, BarrierSettings(), REFERENCE_BODY)
    assert clipped["natural_barriers"] == {
        "enabled": True,
        "active": 1,
        "types": ["sea"],
    }
    clipped_60 = next(f for f in clipped["forecasts"] if f["horizon_minutes"] == 60)[
        "area_ha"
    ]
    assert clipped_60 == 23.189
    assert clipped_60 < baseline_60


def test_predict_barriers_can_be_switched_off(session):
    register_barrier(session, _sea(500.0))
    off = predict_spread(session, BarriersOffSettings(), REFERENCE_BODY)
    off_60 = next(f for f in off["forecasts"] if f["horizon_minutes"] == 60)
    assert off_60["area_ha"] == 27.518
    assert off["natural_barriers"]["enabled"] is False
    assert off["natural_barriers"]["active"] == 0


def test_uncertainty_envelope_rings_respect_barriers(session):
    register_barrier(session, _sea(500.0))
    barriers = _load(session)  # reload through DB like the engine does
    assert len(barriers) == 1
    envelope = envelope_from_inputs(session, BarrierSettings(), REFERENCE_INPUTS, [60])
    assert envelope["natural_barriers"] == {"enabled": True, "active": 1}
    band = envelope["horizons"][0]
    # Pessimistic ring (946.6 m head) is truncated at the 500 m shoreline.
    pess_ring = band["pessimistic"]["polygon_geojson"]["coordinates"][0]
    max_north_lat = max(p[1] for p in pess_ring)
    # +1e-5 deg tolerance: project_polygon rounds metres back to 6-decimal degrees.
    assert max_north_lat <= LAT0 + 500.0 / M_PER_DEG + 1e-5
    assert band["pessimistic"]["area_ha"] < 48.162  # unmasked EM-020 anchor


# --- REST endpoints and map layer ----------------------------------------------------


def test_barrier_endpoints_crud(client):
    created = client.post("/api/v1/spread/barriers", json=_sea(500.0))
    assert created.status_code == 200
    assert created.json()["barrier_key"] == "SEA-1"
    assert created.json()["slowdown_factor"] == 0.0
    assert created.json()["is_active"] is True
    listing = client.get("/api/v1/spread/barriers")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    bad = client.post(
        "/api/v1/spread/barriers", json=dict(_sea(500.0), barrier_type="nehir")
    )
    assert bad.status_code == 400
    assert client.delete("/api/v1/spread/barriers/SEA-1").status_code == 200
    assert client.delete("/api/v1/spread/barriers/SEA-1").status_code == 404


def test_barriers_map_layer_mixed_geometry(session):
    _load(session, _sea(500.0), _road(300.0))
    layer = build_layer(session, BarrierSettings(), "barriers")
    assert layer["layer"] == "barriers"
    assert layer["count"] == 2
    assert "EM-021" in layer["attribution"]
    by_type = {f["properties"]["barrier_type"]: f for f in layer["features"]}
    assert by_type["sea"]["geometry"]["type"] == "Polygon"
    assert by_type["sea"]["properties"]["blocks_spread"] is True
    assert by_type["road"]["geometry"]["type"] == "LineString"
    assert by_type["road"]["properties"]["blocks_spread"] is False


def test_barriers_layer_endpoint(client):
    response = client.get("/api/v1/map/layers/barriers")
    assert response.status_code == 200
    assert response.json()["title"] == "Doğal Engeller"
