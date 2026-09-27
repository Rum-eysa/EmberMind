"""USGS/SRTM topography calculation, caching, and persistence unit tests."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from src.models.fire import FireCluster
from src.models.topography import TopographyDataPoint
from src.services.topography import (
    SRTMTopographyClient,
    TopographySourceError,
    sync_topography_for_clusters,
)


class _FakeResponse:
    """Minimal stand-in for requests.Response used by the topography client."""

    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def _elevated(north: float, south: float, east: float, west: float) -> _FakeResponse:
    """Canned lookup for the 5-point grid: center, north, south, east, west."""
    values = [100.0, north, south, east, west]
    return _FakeResponse(200, {"results": [{"elevation": v} for v in values]})


def _stub_client(payload: dict[str, Any]) -> SRTMTopographyClient:
    def fake_post(url: str, json: Any = None, timeout: Any = None) -> _FakeResponse:
        return _FakeResponse(200, payload)

    return SRTMTopographyClient(http_post=fake_post)


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

    # Eastward rising slope (downslope faces West = 270 deg)
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


def test_aspect_is_downslope_bearing_north_south_and_diagonal():
    """Aspect must be the downslope compass bearing (regression: N/S mirror bug)."""
    client = SRTMTopographyClient(resolution_meters=30)

    # Higher to the north -> water drains south -> aspect 180 (south-facing).
    _, aspect = client.calculate_slope_and_aspect(
        {"center": 100.0, "north": 130.0, "south": 70.0, "east": 100.0, "west": 100.0}
    )
    assert aspect == 180.0

    # Higher to the south -> downslope north -> aspect 0.
    _, aspect = client.calculate_slope_and_aspect(
        {"center": 100.0, "north": 70.0, "south": 130.0, "east": 100.0, "west": 100.0}
    )
    assert aspect == 0.0

    # Higher to the north-east -> downslope south-west -> aspect 225.
    _, aspect = client.calculate_slope_and_aspect(
        {"center": 100.0, "north": 120.0, "south": 80.0, "east": 120.0, "west": 80.0}
    )
    assert aspect == 225.0


def test_topography_region_caching():
    client = _stub_client(
        {"results": [{"elevation": v} for v in (100.0, 130.0, 70.0, 100.0, 100.0)]}
    )
    lat, lon = 39.9, 32.8

    res1 = client.fetch_topography(lat, lon)
    res2 = client.fetch_topography(lat, lon)

    assert res1.latitude == res2.latitude
    assert res1.elevation == res2.elevation == 100.0
    assert res1.slope == res2.slope
    assert res1.aspect == res2.aspect == 180.0
    assert res1.resolution_meters == 30
    assert res1.source == "USGS/SRTM"


def test_topography_raises_instead_of_fabricating_terrain():
    """Non-200 / unreachable / incomplete lookups must fail loudly, never invent DEM."""
    import requests

    def fail_post(url: str, json: Any = None, timeout: Any = None) -> Any:
        raise requests.ConnectionError("service down")

    client = SRTMTopographyClient(http_post=fail_post)
    try:
        client.fetch_topography(39.9, 32.8)
        raise AssertionError("expected TopographySourceError")
    except TopographySourceError:
        pass

    down = SRTMTopographyClient(http_post=lambda *a, **k: _FakeResponse(503, {}))
    try:
        down.fetch_topography(39.9, 32.8)
        raise AssertionError("expected TopographySourceError")
    except TopographySourceError:
        pass

    partial = SRTMTopographyClient(
        http_post=lambda *a, **k: _FakeResponse(
            200, {"results": [{"elevation": 100.0}] * 3}
        )
    )
    try:
        partial.fetch_topography(39.9, 32.8)
        raise AssertionError("expected TopographySourceError")
    except TopographySourceError:
        pass


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

        stub = SRTMTopographyClient(
            http_post=lambda *a, **k: _elevated(130, 70, 100, 100)
        )
        result = sync_topography_for_clusters(session, api.state.settings, client=stub)
        assert result["clusters_processed"] == 1
        assert result["topography_points_saved"] == 1

        points = session.scalars(select(TopographyDataPoint)).all()
        assert len(points) == 1
        assert points[0].cluster_key == "cluster_topo_test_1"
        assert points[0].resolution_meters == 30
        assert points[0].elevation == 100.0
        assert points[0].slope > 0.0
        assert points[0].aspect == 180.0  # north-high -> south-facing


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
