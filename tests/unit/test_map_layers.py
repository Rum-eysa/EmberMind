"""EM-072 operator map layer tests (GeoJSON feeds + Leaflet UI page)."""
from src.models.fire import FireCluster
from src.models.inventory import SuppressionResource
from src.models.land_cover import LandCoverDataPoint
from src.models.road_network import CrewBase, RoadSegment
from src.models.spatial import FireEvent, SilentRegion
from src.services.map_layers import (
    MapLayerError,
    bbox_ring,
    build_layer,
    forecasts_layer,
    layer_catalog,
    parse_polygon_wkt,
)
from src.services.spread import predict_spread
from src.utils.timeutils import utc_now


class SpreadSettings:
    """Settings stub for the spread engine used to seed forecasts."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = False


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


def _seed_map_data(session):
    """Store one feature for every non-forecast layer."""
    now = utc_now()
    session.add(
        FireCluster(
            cluster_key="CL-072",
            latitude=37.1,
            longitude=28.1,
            observation_count=3,
            max_frp=12.5,
            first_seen_at=now,
            last_seen_at=now,
            sources="VIIRS_SNPP_NRT",
        )
    )
    session.add(
        FireEvent(
            event_key="EVT-072",
            name="Çamköy Yangını",
            latitude=37.2,
            longitude=28.2,
            min_lat=37.15,
            max_lat=37.25,
            min_lon=28.15,
            max_lon=28.25,
            geometry_wkt="POLYGON((28.15 37.15, 28.25 37.25))",
            severity="high",
            status="active",
            started_at=now,
            source="manual",
        )
    )
    session.add(
        LandCoverDataPoint(
            cluster_key="CL-072",
            latitude=37.1,
            longitude=28.1,
            corine_code=311,
            land_cover_class="kızılçam",
            fuel_model="FM10_RedPine",
            spread_factor=1.8,
            fetched_at=now,
        )
    )
    session.add(
        SilentRegion(
            region_name="Sessiz Kuşak Batı",
            reason="uydu görüş açısı kısıtı",
            min_lat=37.0,
            max_lat=37.5,
            min_lon=27.5,
            max_lon=28.0,
            geometry_wkt="POLYGON((27.5 37.0, 28.0 37.0, 28.0 37.5, 27.5 37.5, 27.5 37.0))",
            is_active=True,
        )
    )
    session.add(
        SilentRegion(
            region_name="Sessiz Kuşak Doğu",
            reason="radar gölgesi",
            min_lat=37.6,
            max_lat=38.0,
            min_lon=28.4,
            max_lon=28.8,
            geometry_wkt="",  # forces the bbox fallback ring
            is_active=True,
        )
    )
    session.add(
        CrewBase(
            base_key="BASE-072",
            name="Ormanyalanı Müdahale Merkezi",
            latitude=37.3,
            longitude=28.05,
            crew_type="first_response",
            available=True,
        )
    )
    session.add(
        RoadSegment(
            segment_key="SEG-072",
            osm_way_id=123456,
            from_node_id=1,
            to_node_id=2,
            from_lat=37.3,
            from_lon=28.05,
            to_lat=37.35,
            to_lon=28.1,
            name="D550",
            highway="primary",
            length_km=4.2,
            max_speed_kmh=90.0,
            one_way=False,
            fetched_at=now,
        )
    )
    session.commit()


def test_parse_polygon_wkt_valid_empty_and_malformed():
    ring = parse_polygon_wkt("POLYGON((28.0 37.0, 28.1 37.0, 28.05 37.1, 28.0 37.0))")
    assert len(ring) == 4
    assert ring[0] == [28.0, 37.0]
    assert parse_polygon_wkt("POLYGON(EMPTY)") == []
    assert parse_polygon_wkt("") == []
    assert parse_polygon_wkt(None) == []
    assert parse_polygon_wkt("POINT(1 2)") == []
    assert parse_polygon_wkt("POLYGON((a b, c d))") == []


def test_bbox_ring_is_closed_counter_clockwise():
    ring = bbox_ring(37.0, 38.0, 28.0, 29.0)
    assert ring[0] == [28.0, 37.0]
    assert ring[-1] == ring[0]
    assert len(ring) == 5


def test_fires_layer_includes_clusters_and_events(session):
    _seed_map_data(session)
    layer = build_layer(session, None, "fires")
    assert layer["type"] == "FeatureCollection"
    kinds = {f["properties"]["kind"] for f in layer["features"]}
    assert kinds == {"satellite_cluster", "fire_event"}
    event = next(
        f for f in layer["features"] if f["properties"]["kind"] == "fire_event"
    )
    assert event["geometry"]["coordinates"] == [28.2, 37.2]
    assert event["properties"]["severity"] == "high"


def test_forecasts_layer_horizon_and_event_filter(session):
    _seed_map_data(session)
    predict_spread(session, SpreadSettings(), {**REFERENCE, "event_key": "EVT-072"})
    all_features = forecasts_layer(session)["features"]
    assert {f["properties"]["horizon_minutes"] for f in all_features} == {30, 60, 120}
    for feature in all_features:
        assert feature["geometry"]["type"] == "Polygon"
        assert len(feature["geometry"]["coordinates"][0]) == 37
    only_60 = forecasts_layer(session, horizon_minutes=60)["features"]
    assert len(only_60) == 1
    assert only_60[0]["properties"]["horizon_minutes"] == 60
    other_event = forecasts_layer(session, event_key="EVT-YOK")["features"]
    assert other_event == []


def test_fuel_layer_carries_fuel_class_properties(session):
    _seed_map_data(session)
    layer = build_layer(session, None, "fuel")
    assert layer["count"] == 1
    props = layer["features"][0]["properties"]
    assert props["fuel_model"] == "FM10_RedPine"
    assert props["spread_factor"] == 1.8


def test_silent_regions_use_wkt_or_bbox_fallback(session):
    _seed_map_data(session)
    layer = build_layer(session, None, "silent-regions")
    by_name = {f["properties"]["region_name"]: f for f in layer["features"]}
    assert len(by_name) == 2
    wkt_ring = by_name["Sessiz Kuşak Batı"]["geometry"]["coordinates"][0]
    assert wkt_ring[0] == [27.5, 37.0]
    bbox = by_name["Sessiz Kuşak Doğu"]["geometry"]["coordinates"][0]
    assert bbox[0] == [28.4, 37.6] and bbox[-1] == bbox[0]


def test_resources_and_roads_layers(session):
    _seed_map_data(session)
    session.add(
        SuppressionResource(
            resource_key="IHA-072",
            name="Keşif İHA",
            resource_type="uav",
            latitude=37.0,
            longitude=28.0,
            status="deployed",
            capacity=2.0,
        )
    )
    session.commit()
    resources = build_layer(session, None, "resources")
    # Crew bases come first, then EM-103 inventory assets (distinguished by kind).
    assert resources["features"][0]["properties"]["available"] is True
    assert resources["features"][0]["properties"]["kind"] == "crew_base"
    assets = [
        f
        for f in resources["features"]
        if f["properties"]["kind"] == "suppression_resource"
    ]
    assert len(assets) == 1
    assert assets[0]["properties"]["resource_type"] == "uav"
    assert assets[0]["properties"]["available"] is False
    assert "EM-103" in resources["attribution"]
    roads = build_layer(session, None, "roads")
    road = roads["features"][0]
    assert road["geometry"]["type"] == "LineString"
    assert road["geometry"]["coordinates"][0] == [28.05, 37.3]
    assert road["properties"]["name"] == "D550"


def test_build_layer_unknown_name_raises(session):
    try:
        build_layer(session, None, "radyolar")
        raise AssertionError("expected MapLayerError")
    except MapLayerError as exc:
        assert "unknown map layer" in str(exc)


def test_layer_catalog_lists_seven_toggleable_layers():
    catalog = layer_catalog()
    keys = {item["key"] for item in catalog}
    assert keys == {
        "fires",
        "forecasts",
        "uncertainty",
        "fuel",
        "silent-regions",
        "resources",
        "roads",
    }
    for item in catalog:
        assert item["url"] == f"/api/v1/map/layers/{item['key']}"
        assert item["geometry"] in ("Point", "Polygon", "LineString")


def test_map_layers_endpoint_catalog(client):
    response = client.get("/api/v1/map/layers")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 7


def test_map_layer_endpoint_and_unknown_layer(client):
    ok = client.get("/api/v1/map/layers/fires")
    assert ok.status_code == 200
    assert ok.json()["type"] == "FeatureCollection"
    missing = client.get("/api/v1/map/layers/kahve_molasi")
    assert missing.status_code == 404
    assert "unknown map layer" in missing.json()["detail"]["error"]


def test_map_forecast_endpoint_horizon_filter(client):
    predict = client.post(
        "/api/v1/spread/predict",
        json={**REFERENCE, "event_key": "EVT-API-072"},
    )
    assert predict.status_code == 200
    response = client.get(
        "/api/v1/map/layers/forecasts", params={"horizon_minutes": 120}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["features"][0]["properties"]["horizon_minutes"] == 120
    assert body["attribution"]


def test_ui_page_served_with_toggles_and_slider(client):
    response = client.get("/ui")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    # Katman anahtarları (Leaflet layer control) ve zaman kaydırıcısı.
    assert 'id="horizon-slider"' in html
    assert "L.control.layers" in html
    for title in ("Aktif Yangınlar", "Risk Bölgeleri", "Yakıt"):
        assert title in html or "forecasts" in html
    assert "/api/v1/map/layers" in html


def test_root_redirects_to_operator_map(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/ui"
