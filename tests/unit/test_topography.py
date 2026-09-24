"""USGS/SRTM topography calculation, caching, and persistence unit tests."""
from datetime import datetime, timezone

import pytest

from sqlalchemy import select

from src.models.fire import FireCluster
from src.models.topography import TopographyDataPoint
from src.services.topography import SRTMTopographyClient, sync_topography_for_clusters


def test_topography_slope_and_aspect_calculation():
    client = SRTMTopographyClient(resolution_meters=30)

    # Flat terrain
    flat_elevations = {
        "center": 100.0,
        "north": 100.0,
        "south": 100.0,
        "east": 100.0,
        "west": 100.0,
    }
    slope, aspect = client.calculate_slope_and_aspect(flat_elevations)
    assert slope == 0.0
    assert aspect == 0.0

    # Eastward rising slope (facing West = 270 deg)
    east_slope_elevations = {
        "center": 100.0,
        "north": 100.0,
        "south": 100.0,
        "east": 130.0,
        "west": 70.0,
    }
    slope, aspect = client.calculate_slope_and_aspect(east_slope_elevations)
    assert slope > 0.0
    assert aspect == 270.0


def test_topography_region_caching():
    client = SRTMTopographyClient(cache_ttl_seconds=3600)
    lat, lon = 39.9, 32.8

    res1 = client.fetch_topography(lat, lon)
    res2 = client.fetch_topography(lat, lon)

    assert res1.latitude == res2.latitude
    assert res1.longitude == res2.longitude
    assert res1.elevation == res2.elevation
    assert res1.slope == res2.slope
    assert res1.aspect == res2.aspect
    assert res1.resolution_meters == 30
    assert res1.source == "USGS/SRTM"


def test_sync_topography_for_clusters_persists_to_db(client, api):
    database = api.state.database

    with database.session() as session:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cluster = FireCluster(
            cluster_key="cluster_topo_test_1",
            latitude=39.9,
            longitude=32.8,
            observation_count=5,
            max_frp=120.0,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(cluster)
        session.commit()

        result = sync_topography_for_clusters(session, api.state.settings)
        assert result["clusters_processed"] == 1
        assert result["topography_points_saved"] == 1

        points = session.scalars(select(TopographyDataPoint)).all()
        assert len(points) == 1
        assert points[0].cluster_key == "cluster_topo_test_1"
        assert points[0].resolution_meters == 30
        assert points[0].elevation >= 0.0
        assert 0.0 <= points[0].slope <= 90.0
        assert 0.0 <= points[0].aspect <= 360.0


def test_fastapi_topography_endpoints(client):
    # Sync topography endpoint
    sync_resp = client.post("/api/v1/topography/sync")
    assert sync_resp.status_code == 200
    assert sync_resp.json()["status"] == "ok"

    # Get topography endpoint
    get_resp = client.get("/api/v1/topography")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["source"] == "USGS/SRTM"
    assert isinstance(data["topography_data"], list)
