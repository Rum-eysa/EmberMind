"""EM-023 exposure/threat-analysis tests.

Covers OpenStreetMap asset parsing/import guards, the forecast-polygon
intersection that yields an interpolated first-impact time (T+dk), the
priority-scored commander list, the bbox pre-filter and TTL cache, the GeoJSON
map layer and the HTTP endpoints (including import validation).
"""
import json

from src.models.exposure import ExposedAsset
from src.models.road_network import RoadSegment
from src.models.spatial import FireForecast
from src.services.exposure import (
    _ANALYSIS_CACHE,
    ExposureOverpassClient,
    NormalizedAsset,
    analyze_exposure,
    bbox_area_deg2,
    exposure_layer,
    exposure_summary,
    filter_assets,
    parse_asset_response,
    sync_exposed_assets,
    upsert_assets,
    _interpolate_impact,
    _priority_score,
)
from src.services.map_layers import build_layer, layer_catalog
from src.utils.timeutils import utc_now


class _Settings:
    """Minimal settings stub for the exposure service (cache off for isolation)."""

    OVERPASS_BASE_URL = "https://example.invalid/api"
    EXPOSURE_CACHE_ENABLED = False


class _CacheSettings(_Settings):
    """Same stub but with the analysis TTL cache enabled."""

    EXPOSURE_CACHE_ENABLED = True
    EXPOSURE_CACHE_TTL_SECONDS = 3600.0


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


def _add_asset(session, key, atype, name, lat, lon, wkt, tags=None, source="test"):
    session.add(
        ExposedAsset(
            asset_key=key,
            asset_type=atype,
            name=name,
            osm_id=None,
            latitude=lat,
            longitude=lon,
            min_lat=min(lat, lat),
            max_lat=lat,
            min_lon=lon,
            max_lon=lon,
            geometry_wkt=wkt,
            tags_json=json.dumps(tags or {}),
            source=source,
            fetched_at=utc_now(),
        )
    )


def _seed_forecasts_at(session, event, lat, lon, rate=10.0):
    """Insert 30/60/120 min square horizon polygons around ``(lat, lon)``."""
    for horizon, half in ((30, 0.01), (60, 0.02), (120, 0.04)):
        session.add(
            FireForecast(
                event_key=event,
                model_name="rothermel_v1",
                latitude=lat,
                longitude=lon,
                predicted_area_ha=half * 100,
                geometry_wkt=_square_wkt(lat, lon, half),
                forecast_for=utc_now(),
                horizon_minutes=horizon,
                rate_of_spread_m_per_min=rate,
                spread_direction_deg=45.0,
                inputs_json=json.dumps({"fuel_moisture_pct": 8.0}),
            )
        )


def _seed_forecasts(session, event="EVT-A"):
    _seed_forecasts_at(session, event, 38.0, 27.0)


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
    assert settlement.tags["named"] is True
    line = by_key["osm-way-700"]
    assert line.asset_type == "power_line"
    assert line.geometry_wkt.startswith("LINESTRING")
    assert line.tags["voltage"] == "154000"
    assert "partial" not in line.tags


def test_parse_asset_response_flags_partial_power_line():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 38.0, "lon": 27.0},
            # node 2 coordinate is absent -> the way is truncated.
            {"type": "way", "id": 700, "nodes": [1, 2, 3], "tags": {"power": "line"}},
            {"type": "node", "id": 3, "lat": 38.05, "lon": 27.05},
        ]
    }
    assets = parse_asset_response(payload)
    line = next(a for a in assets if a.asset_key == "osm-way-700")
    assert line.tags.get("partial") is True


def test_parse_asset_response_ignores_non_place_nodes():
    payload = {
        "elements": [{"type": "node", "id": 9, "lat": 1.0, "lon": 1.0, "tags": {}}]
    }
    assert parse_asset_response(payload) == []


def test_bbox_area_deg2():
    assert abs(bbox_area_deg2((38.0, 27.0, 38.5, 27.4)) - 0.2) < 1e-9
    assert abs(bbox_area_deg2((38.0, 27.0, 39.0, 28.0)) - 1.0) < 1e-9


def test_filter_assets_priority_classes_and_cap():
    def _s(key, named, place):
        return NormalizedAsset(
            asset_key=key,
            asset_type="settlement",
            name=key,
            osm_id=1,
            latitude=38.0,
            longitude=27.0,
            geometry_wkt="POINT(27.0 38.0)",
            tags={"named": named, "place": place},
        )

    assets = [
        _s("named", True, "hamlet"),
        _s("anon_village", False, "village"),
        _s("anon_hamlet", False, "hamlet"),
    ]
    kept = filter_assets(assets, priority_classes=["village"])
    keys = {a.asset_key for a in kept}
    assert keys == {"named", "anon_village"}
    # No configured classes -> everything survives (offline-test default).
    assert len(filter_assets(assets, priority_classes=[])) == 3
    # Hard cap truncates.
    assert len(filter_assets(assets, priority_classes=None, max_assets=2)) == 2


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
    assert result == {
        "assets_fetched": 1,
        "assets_kept": 1,
        "assets_skipped": 0,
        "assets_saved": 1,
    }
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


# ----------------------------------------------------- impact math ------


def test_interpolate_impact_brackets_between_horizons():
    # Element halfway between the 30- and 60-min head fronts -> ~45 min.
    assert _interpolate_impact(300.0, 30, 600.0, 60, 450.0) == 45
    # Beyond the current head front -> clamps up to the containing horizon.
    assert _interpolate_impact(300.0, 30, 600.0, 60, 1000.0) == 60
    # Inside the previous front -> clamps down to the previous horizon.
    assert _interpolate_impact(300.0, 30, 600.0, 60, 100.0) == 30
    # Degenerate (no spread rate) -> fall back to the horizon bucket.
    assert _interpolate_impact(0.0, 0, 0.0, 30, 500.0) == 30


def test_priority_score_prefers_sooner_and_larger():
    sooner = {
        "asset_type": "settlement",
        "first_impact_minutes": 10,
        "population": 500,
    }
    later = {
        "asset_type": "settlement",
        "first_impact_minutes": 100,
        "population": 500,
    }
    assert _priority_score(sooner, 120, 100000) > _priority_score(later, 120, 100000)
    big = {"asset_type": "settlement", "first_impact_minutes": 30, "population": 50000}
    small = {"asset_type": "settlement", "first_impact_minutes": 30, "population": 50}
    assert _priority_score(big, 120, 100000) > _priority_score(small, 120, 100000)
    # Energy lines outrank plain roads at equal impact/population.
    line = {"asset_type": "power_line", "first_impact_minutes": 30, "population": None}
    road = {"asset_type": "road", "first_impact_minutes": 30, "population": None}
    assert _priority_score(line, 120, 100000) > _priority_score(road, 120, 100000)


# ------------------------------------------------------------- analysis ---


def test_analyze_exposure_first_impact_and_sorting(session):
    _seed_forecasts(session)
    # A settlement just inside the 30-min polygon (off the exact origin so the
    # interpolated arrival clamps to the 30-min bucket).
    _add_asset(
        session,
        "in30",
        "settlement",
        "Merkez",
        38.004,
        27.0,
        "POINT(27.0 38.004)",
        {"population": 500},
    )
    _add_asset(
        session, "in60", "settlement", "Dış mahalle", 38.015, 27.0, "POINT(27.0 38.015)"
    )
    _add_asset(session, "far", "settlement", "Uzak", 38.06, 27.0, "POINT(27.0 38.06)")
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
    assert keys["in30"]["impact_horizon_minutes"] == 30
    assert keys["in30"]["asset_type"] == "settlement"
    assert keys["in30"]["population"] == 500
    assert keys["in30"]["source"] == "test"
    assert keys["in60"]["first_impact_minutes"] == 60
    assert keys["in60"]["impact_horizon_minutes"] == 60
    assert keys["line"]["impact_horizon_minutes"] == 30
    assert keys["line"]["first_impact_minutes"] <= 30
    assert keys["road-r60"]["asset_type"] == "road"
    assert keys["road-r60"]["first_impact_minutes"] == 60
    # Every item exposes a priority score and impact time.
    for item in items:
        assert isinstance(item["priority_score"], float)
        assert 0 <= item["first_impact_minutes"] <= 120
    # Sorted by protection/evacuation priority (highest first).
    scores = [item["priority_score"] for item in items]
    assert scores == sorted(scores, reverse=True)


def test_analyze_exposure_event_filter(session):
    _seed_forecasts_at(session, "EVT-A", 38.0, 27.0)
    _seed_forecasts_at(session, "EVT-B", 37.0, 26.0)
    _add_asset(session, "a", "settlement", "A köyü", 38.004, 27.0, "POINT(27.0 38.004)")
    _add_asset(session, "b", "settlement", "B köyü", 37.004, 26.0, "POINT(26.0 37.004)")
    session.flush()

    both = {item["asset_key"] for item in analyze_exposure(session, _Settings())}
    assert both == {"a", "b"}
    only_a = {
        item["asset_key"] for item in analyze_exposure(session, _Settings(), "EVT-A")
    }
    assert only_a == {"a"}
    only_b = {
        item["asset_key"] for item in analyze_exposure(session, _Settings(), "EVT-B")
    }
    assert only_b == {"b"}


def test_analyze_exposure_cache_invalidates_on_change(session):
    _ANALYSIS_CACHE.clear()
    try:
        _seed_forecasts(session)
        _add_asset(
            session, "a", "settlement", "Köy A", 38.004, 27.0, "POINT(27.0 38.004)"
        )
        session.flush()
        first = analyze_exposure(session, _CacheSettings())
        assert {i["asset_key"] for i in first} == {"a"}
        # A cached second call returns the same content.
        assert {
            i["asset_key"] for i in analyze_exposure(session, _CacheSettings())
        } == {"a"}
        # Adding an asset changes the fingerprint -> recomputed.
        _add_asset(
            session, "b", "settlement", "Köy B", 38.005, 27.0, "POINT(27.0 38.005)"
        )
        session.flush()
        second = {i["asset_key"] for i in analyze_exposure(session, _CacheSettings())}
        assert second == {"a", "b"}
    finally:
        _ANALYSIS_CACHE.clear()


def test_analyze_exposure_no_forecasts_returns_empty(session):
    _add_asset(session, "in30", "settlement", "Merkez", 38.0, 27.0, "POINT(27.0 38.0)")
    session.flush()
    assert analyze_exposure(session, _Settings()) == []


def test_exposure_summary_counts(session):
    _seed_forecasts(session)
    _add_asset(session, "a", "settlement", "Köy", 38.004, 27.0, "POINT(27.0 38.004)")
    _add_asset(
        session,
        "b",
        "power_line",
        "Hat",
        38.004,
        27.0,
        "LINESTRING(26.999 38.004,27.001 38.004)",
    )
    session.flush()
    summary = exposure_summary(session, _Settings())
    assert summary["count"] == 2
    assert summary["earliest_impact_minutes"] == 30
    assert summary["by_type"] == {"settlement": 1, "power_line": 1}
    assert all("geometry" not in item for item in summary["items"])
    assert all("priority_score" in item for item in summary["items"])


def test_exposure_layer_is_featurecollection(session):
    _seed_forecasts(session)
    _add_asset(session, "a", "settlement", "Köy", 38.004, 27.0, "POINT(27.0 38.004)")
    session.flush()
    layer = exposure_layer(session, _Settings())
    assert layer["type"] == "FeatureCollection"
    assert layer["layer"] == "exposure"
    assert layer["count"] == 1
    feature = layer["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["first_impact_minutes"] == 30
    assert feature["properties"]["priority_score"] is not None


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
    _add_asset(session, "a", "settlement", "Köy", 38.004, 27.0, "POINT(27.0 38.004)")
    session.flush()
    layer = build_layer(session, _Settings(), "exposure")
    assert layer["count"] == 1


def test_build_layer_exposure_event_filter(session):
    _seed_forecasts_at(session, "EVT-A", 38.0, 27.0)
    _seed_forecasts_at(session, "EVT-B", 37.0, 26.0)
    _add_asset(session, "a", "settlement", "A", 38.004, 27.0, "POINT(27.0 38.004)")
    _add_asset(session, "b", "settlement", "B", 37.004, 26.0, "POINT(26.0 37.004)")
    session.flush()
    layer = build_layer(session, _Settings(), "exposure", None, "EVT-B")
    assert {f["properties"]["asset_key"] for f in layer["features"]} == {"b"}


# ----------------------------------------------------------------- api ---


def test_exposure_endpoints(client, session):
    _seed_forecasts(session)
    _add_asset(
        session,
        "a",
        "settlement",
        "Çamköy",
        38.004,
        27.0,
        "POINT(27.0 38.004)",
        {"population": 500},
    )
    _add_asset(session, "far", "settlement", "Uzak", 38.06, 27.0, "POINT(27.0 38.06)")
    session.flush()

    listing = client.get("/api/v1/exposure")
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    assert body["items"][0]["name"] == "Çamköy"
    assert body["items"][0]["first_impact_minutes"] == 30
    assert "priority_score" in body["items"][0]

    filtered = client.get("/api/v1/exposure", params={"event_key": "EVT-A"})
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1

    empty = client.get("/api/v1/exposure", params={"event_key": "NO-SUCH"})
    assert empty.status_code == 200
    assert empty.json()["count"] == 0

    layer = client.get("/api/v1/map/layers/exposure")
    assert layer.status_code == 200
    assert layer.json()["features"][0]["properties"]["asset_type"] == "settlement"

    catalog = client.get("/api/v1/map/layers")
    assert catalog.status_code == 200
    keys = [entry["key"] for entry in catalog.json()["layers"]]
    assert "exposure" in keys


def test_exposure_import_rejects_oversized_bbox(client):
    response = client.post(
        "/api/v1/exposure/import",
        json={"min_lat": 30.0, "min_lon": 20.0, "max_lat": 45.0, "max_lon": 45.0},
    )
    assert response.status_code == 400
    assert "deg^2" in response.json()["detail"]["error"]


def test_exposure_import_rejects_inverted_bbox(client):
    response = client.post(
        "/api/v1/exposure/import",
        json={"min_lat": 39.0, "min_lon": 27.0, "max_lat": 36.0, "max_lon": 28.0},
    )
    assert response.status_code == 400
