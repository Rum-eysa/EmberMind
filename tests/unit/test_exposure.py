"""EM-023 exposure/threat-analysis tests.

Covers OpenStreetMap asset parsing/import, the forecast-polygon intersection
that yields a first-impact time (T+dk), the sorted commander list, the GeoJSON
map layer and the HTTP endpoints.
"""
import json

from src.models.exposure import ExposedAsset
from src.models.road_network import RoadSegment
from src.models.spatial import FireForecast
from src.services.exposure import (
    ExposureOverpassClient,
    analyze_exposure,
    exposure_layer,
    exposure_summary,
    parse_asset_response,
    sync_exposed_assets,
    upsert_assets,
)
from src.services.map_layers import build_layer, layer_catalog
from src.utils.timeutils import utc_now


class _Settings:
    """Minimal settings stub for the exposure service."""

    OVERPASS_BASE_URL = "https://example.invalid/api"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _square_wkt(lat, lon, half):
    return (
        f"POLYGON(({lon - half} {lat - half},{lon + half} {lat - half},"
        f"{lon + half} {lat + half},{lon - half} {lat + half},"
        f"{lon - half} {lat - half}))"
    )


def _add_asset(session, key, atype, name, lat, lon, wkt, tags=None):
    session.add(
        ExposedAsset(
            asset_key=key,
            asset_type=atype,
            name=name,
            osm_id=None,
            latitude=lat,
            longitude=lon,
            min_lat=lat,
            max_lat=lat,
            min_lon=lon,
            max_lon=lon,
            geometry_wkt=wkt,
            tags_json=json.dumps(tags or {}),
            source="test",
            fetched_at=utc_now(),
        )
    )


def _seed_forecasts(session, event="EVT-A"):
    for horizon, half in ((30, 0.01), (60, 0.02), (120, 0.04)):
        session.add(
            FireForecast(
                event_key=event,
                model_name="rothermel_v1",
                latitude=38.0,
                longitude=27.0,
                predicted_area_ha=half * 100,
                geometry_wkt=_square_wkt(38.0, 27.0, half),
                forecast_for=utc_now(),
                horizon_minutes=horizon,
                rate_of_spread_m_per_min=10.0,
                spread_direction_deg=45.0,
                inputs_json=json.dumps({"fuel_moisture_pct": 8.0}),
            )
        )


# ---------------------------------------------------------- OSM parsing ---


def test_parse_asset_response_settlement_and_power_line():
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 5001,
                "lat": 38.0,
                "lon": 27.0,
                "tags": {"place": "village", "name": "Çamköy", "population": "420"},
            },
            {"type": "node", "id": 1, "lat": 38.0, "lon": 27.0},
            {"type": "node", "id": 2, "lat": 38.01, "lon": 27.01},
            {
                "type": "way",
                "id": 700,
                "nodes": [1, 2],
                "tags": {"power": "line", "voltage": "154000"},
            },
        ]
    }
    assets = parse_asset_response(payload)
    by_key = {a.asset_key: a for a in assets}
    settlement = by_key["osm-node-5001"]
    assert settlement.asset_type == "settlement"
    assert settlement.name == "Çamköy"
    assert settlement.tags["population"] == 420
    line = by_key["osm-way-700"]
    assert line.asset_type == "power_line"
    assert line.geometry_wkt.startswith("LINESTRING")
    assert line.tags["voltage"] == "154000"


def test_parse_asset_response_ignores_non_place_nodes():
    payload = {
        "elements": [{"type": "node", "id": 9, "lat": 1.0, "lon": 1.0, "tags": {}}]
    }
    assert parse_asset_response(payload) == []


def test_sync_exposed_assets_persists_with_fake_client(session):
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 4242,
                "lat": 37.5,
                "lon": 28.0,
                "tags": {"place": "town", "name": "Test kasabası", "population": "900"},
            }
        ]
    }
    client = ExposureOverpassClient(
        http_get=lambda url, data, timeout: _FakeResponse(payload)
    )
    result = sync_exposed_assets(
        session, _Settings(), (36.0, 26.0, 39.5, 30.0), client=client
    )
    assert result == {"assets_fetched": 1, "assets_saved": 1}
    row = session.query(ExposedAsset).filter_by(asset_key="osm-node-4242").first()
    assert row is not None
    assert row.asset_type == "settlement"
    assert row.min_lat <= row.latitude <= row.max_lat


def test_upsert_assets_is_idempotent(session):
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 111,
                "lat": 37.0,
                "lon": 27.0,
                "tags": {"place": "village", "name": "Köy"},
            }
        ]
    }
    assets = parse_asset_response(payload)
    assert upsert_assets(session, assets) == 1
    assert upsert_assets(session, assets) == 1
    assert session.query(ExposedAsset).count() == 1


# ------------------------------------------------------------- analysis ---


def test_analyze_exposure_first_impact_and_sorting(session):
    _seed_forecasts(session)
    _add_asset(
        session,
        "in30",
        "settlement",
        "Merkez",
        38.0,
        27.0,
        "POINT(27.0 38.0)",
        {"population": 500},
    )
    _add_asset(
        session, "in60", "settlement", "Dış mahalle", 38.015, 27.0, "POINT(27.0 38.015)"
    )
    _add_asset(session, "far", "settlement", "Uzak", 38.05, 27.0, "POINT(27.0 38.05)")
    _add_asset(
        session,
        "line",
        "power_line",
        "Hattı",
        38.0,
        27.0,
        "LINESTRING(26.995 38.0,27.005 38.0)",
    )
    session.add(
        RoadSegment(
            segment_key="r60",
            osm_way_id=1,
            from_node_id=1,
            to_node_id=2,
            from_lat=38.015,
            from_lon=27.0,
            to_lat=38.015,
            to_lon=27.005,
            name="Bağlantı",
            highway="secondary",
            length_km=0.5,
            max_speed_kmh=70.0,
            one_way=False,
            fetched_at=utc_now(),
        )
    )
    session.flush()

    items = analyze_exposure(session, _Settings())
    keys = {item["asset_key"]: item for item in items}
    # The distant settlement is never reached and must be excluded.
    assert "far" not in keys
    assert keys["in30"]["first_impact_minutes"] == 30
    assert keys["in30"]["asset_type"] == "settlement"
    assert keys["in30"]["population"] == 500
    assert keys["in60"]["first_impact_minutes"] == 60
    assert keys["line"]["first_impact_minutes"] == 30
    assert keys["road-r60"]["asset_type"] == "road"
    assert keys["road-r60"]["first_impact_minutes"] == 60
    # Sorted by soonest impact first.
    impacts = [item["first_impact_minutes"] for item in items]
    assert impacts == sorted(impacts)


def test_analyze_exposure_no_forecasts_returns_empty(session):
    _add_asset(session, "in30", "settlement", "Merkez", 38.0, 27.0, "POINT(27.0 38.0)")
    session.flush()
    assert analyze_exposure(session, _Settings()) == []


def test_exposure_summary_counts(session):
    _seed_forecasts(session)
    _add_asset(session, "a", "settlement", "Köy", 38.0, 27.0, "POINT(27.0 38.0)")
    _add_asset(
        session,
        "b",
        "power_line",
        "Hat",
        38.0,
        27.0,
        "LINESTRING(26.999 38.0,27.001 38.0)",
    )
    session.flush()
    summary = exposure_summary(session, _Settings())
    assert summary["count"] == 2
    assert summary["earliest_impact_minutes"] == 30
    assert summary["by_type"] == {"settlement": 1, "power_line": 1}
    assert all("geometry" not in item for item in summary["items"])


def test_exposure_layer_is_featurecollection(session):
    _seed_forecasts(session)
    _add_asset(session, "a", "settlement", "Köy", 38.0, 27.0, "POINT(27.0 38.0)")
    session.flush()
    layer = exposure_layer(session, _Settings())
    assert layer["type"] == "FeatureCollection"
    assert layer["layer"] == "exposure"
    assert layer["count"] == 1
    feature = layer["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["first_impact_minutes"] == 30


# ---------------------------------------------------------------- map ----


def test_exposure_registered_in_layer_catalog():
    catalog = layer_catalog()
    keys = [entry["key"] for entry in catalog]
    assert "exposure" in keys
    entry = next(e for e in catalog if e["key"] == "exposure")
    assert entry["title"] == "Tehdit Altındaki Yapılar"
    assert entry["url"].endswith("/map/layers/exposure")


def test_build_layer_dispatch_exposure(session):
    _seed_forecasts(session)
    _add_asset(session, "a", "settlement", "Köy", 38.0, 27.0, "POINT(27.0 38.0)")
    session.flush()
    layer = build_layer(session, _Settings(), "exposure")
    assert layer["count"] == 1


# ----------------------------------------------------------------- api ---


def test_exposure_endpoints(client, session):
    _seed_forecasts(session)
    _add_asset(
        session,
        "a",
        "settlement",
        "Çamköy",
        38.0,
        27.0,
        "POINT(27.0 38.0)",
        {"population": 500},
    )
    _add_asset(session, "far", "settlement", "Uzak", 38.05, 27.0, "POINT(27.0 38.05)")
    session.flush()

    listing = client.get("/api/v1/exposure")
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    assert body["items"][0]["name"] == "Çamköy"
    assert body["items"][0]["first_impact_minutes"] == 30

    layer = client.get("/api/v1/map/layers/exposure")
    assert layer.status_code == 200
    assert layer.json()["features"][0]["properties"]["asset_type"] == "settlement"

    catalog = client.get("/api/v1/map/layers")
    assert catalog.status_code == 200
    keys = [entry["key"] for entry in catalog.json()["layers"]]
    assert "exposure" in keys
