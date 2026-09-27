"""Pilot region definition, EPSG:4326/UTM coordinate transformation, and 30m grid resampling unit tests."""
from src.services.grid_standard import PilotRegionGridService


def test_pilot_region_bounding_box_and_justification():
    service = PilotRegionGridService()

    # Bounding box bounds (TR-GR coastal line)
    assert service.min_lat == 36.0
    assert service.max_lat == 39.5
    assert service.min_lon == 26.0
    assert service.max_lon == 30.0
    assert service.storage_crs == "EPSG:4326"
    assert service.metric_crs == "EPSG:32635"
    assert "TR-GR" in service.justification or "coastal" in service.justification

    # Inside TR-GR coastal pilot region (e.g. Muğla / Aegean coast)
    assert service.is_within_pilot_region(36.85, 28.27) is True
    # Outside pilot region (e.g. Central Europe)
    assert service.is_within_pilot_region(48.85, 2.35) is False


def test_wgs84_to_utm_35n_projection():
    service = PilotRegionGridService()
    lat, lon = 36.85, 28.27

    easting, northing, crs = service.wgs84_to_utm_35n(lat, lon)
    assert crs == "EPSG:32635"
    # Valid Easting (~600k m) and Northing (~4k km)
    assert 500000.0 <= easting <= 700000.0
    assert 4000000.0 <= northing <= 4500000.0


def test_align_to_30m_grid():
    service = PilotRegionGridService()
    lat, lon = 36.851234, 28.275678

    cell = service.align_to_30m_grid(lat, lon)
    assert cell.resolution_meters == 30
    assert "GRID_30M_" in cell.cell_id
    assert abs(cell.center_lat - lat) < 0.001
    assert abs(cell.center_lon - lon) < 0.001


def test_resample_raster_layer_to_30m():
    service = PilotRegionGridService()
    raw_points = [
        {"latitude": 36.85001, "longitude": 28.27001, "value": 15.0},
        {"latitude": 36.85002, "longitude": 28.27002, "value": 25.0},  # Same 30m cell
        {"latitude": 36.90000, "longitude": 28.35000, "value": 40.0},  # Different cell
    ]

    resampled = service.resample_raster_layer_to_30m(raw_points)
    assert len(resampled) == 2  # 2 distinct 30m grid cells
    assert resampled[0]["resolution_meters"] == 30


def test_resample_uses_unbiased_mean_and_skips_missing_coords():
    """Regression: repeated running-average skewed toward late samples; null
    coordinates used to pool at (0, 0)."""
    service = PilotRegionGridService()
    raw_points = [
        {"latitude": 36.85001, "longitude": 28.27001, "value": 10.0},
        {"latitude": 36.85002, "longitude": 28.27002, "value": 20.0},
        {"latitude": 36.85003, "longitude": 28.27003, "value": 60.0},
        {"latitude": None, "longitude": 28.27, "value": 999.0},  # missing lat
        {"latitude": 36.85, "longitude": None, "value": 999.0},  # missing lon
    ]

    resampled = service.resample_raster_layer_to_30m(raw_points)
    # Only the three valid same-cell points form a single bucket.
    assert len(resampled) == 1
    cell = resampled[0]
    assert cell["sample_count"] == 3
    # True arithmetic mean (10+20+60)/3 = 30, not the order-biased running avg.
    assert cell["value"] == 30.0
    assert "_sum" not in cell


def test_fastapi_grid_endpoints(client):
    # 1. GET pilot region info
    info_resp = client.get("/api/v1/grid/pilot-region")
    assert info_resp.status_code == 200
    data = info_resp.json()
    assert data["coordinate_standards"]["storage_crs"] == "EPSG:4326"
    assert data["coordinate_standards"]["metric_crs"] == "EPSG:32635"
    assert data["grid_specification"]["resolution_meters"] == 30

    # 2. POST transform coordinate
    transform_resp = client.post(
        "/api/v1/grid/transform-coordinate",
        json={"latitude": 36.85, "longitude": 28.27},
    )
    assert transform_resp.status_code == 200
    t_data = transform_resp.json()
    assert t_data["within_pilot_region"] is True
    assert t_data["metric_projection"]["crs"] == "EPSG:32635"
    assert t_data["grid_30m"]["resolution_meters"] == 30

    # 3. POST resample 30m
    resample_resp = client.post(
        "/api/v1/grid/resample-30m",
        json={"points": [{"latitude": 36.85, "longitude": 28.27, "value": 100.0}]},
    )
    assert resample_resp.status_code == 200
    assert resample_resp.json()["resolution_meters"] == 30
