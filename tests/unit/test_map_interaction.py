"""EM-080 map interaction tests (basemaps, place/coordinate search, measure).

Covers the three operator affordances the issue asks for - switch between
street/satellite/terrain basemaps, search a place name *or* a raw coordinate,
and measure a distance/area - plus the config projection and the HTTP
endpoints. Everything is read-only; the maths is checked against analytic
great-circle / spherical-polygon references so the tools are provably correct,
not just non-crashing.
"""
import pytest

from src.services.map_interaction import (
    BASEMAP_KEYS,
    DEFAULT_BASEMAP,
    GAZETTEER,
    MAP_INTERACTION_ATTRIBUTION,
    MAP_INTERACTION_PERSISTENCE,
    MapInteractionError,
    basemap_catalog,
    default_basemap,
    map_interaction_config,
    measure_area,
    measure_distance,
    parse_coordinate,
    search_places,
)


class _Settings:
    """Deterministic map-interaction knobs (fixed default basemap + caps)."""

    def __init__(  # type: ignore[no-untyped-def]
        self,
        *,
        default_basemap=DEFAULT_BASEMAP,
        search_max=8,
        max_points=100,
        coord_format="decimal",
    ):
        self.MAP_DEFAULT_BASEMAP = default_basemap
        self.MAP_SEARCH_MAX_RESULTS = search_max
        self.MAP_MEASURE_MAX_POINTS = max_points
        self.DISPLAY_COORDINATE_FORMAT = coord_format


# ------------------------------------------------------------- basemaps ----


def test_three_basemaps_in_order():
    assert BASEMAP_KEYS == ("street", "satellite", "terrain")
    catalog = basemap_catalog()
    assert [b["key"] for b in catalog] == list(BASEMAP_KEYS)
    for b in catalog:
        assert b["url"] and b["attribution"] and b["label"]
        assert b["max_zoom"] >= 17


def test_default_basemap_is_street():
    assert default_basemap(_Settings()) == "street"
    assert default_basemap(_Settings(default_basemap="terrain")) == "terrain"


def test_default_basemap_rejects_unknown():
    with pytest.raises(MapInteractionError):
        default_basemap(_Settings(default_basemap="watercolor"))


# ----------------------------------------------------------- coordinates ----


@pytest.mark.parametrize(
    "text, lat, lon",
    [
        ("37.03, 27.43", 37.03, 27.43),
        ("37.03 27.43", 37.03, 27.43),
        ("37.03; 27.43", 37.03, 27.43),
        ("37.0°, 27.4°", 37.0, 27.4),
        ("-12.5, -45.0", -12.5, -45.0),
        ("  +8.25 , -1.75 ", 8.25, -1.75),
    ],
)
def test_parse_coordinate_valid(text, lat, lon):
    point = parse_coordinate(text)
    assert point["latitude"] == pytest.approx(lat)
    assert point["longitude"] == pytest.approx(lon)


@pytest.mark.parametrize(
    "text",
    ["Bodrum", "", "37.03", "95, 27", "37, 200", "abc, def", "37.03, 27.43, 100"],
)
def test_parse_coordinate_rejects(text):
    with pytest.raises(MapInteractionError):
        parse_coordinate(text)


# --------------------------------------------------------------- search ----


def test_search_by_place_name():
    result = search_places("Bodrum", _Settings())
    assert result["query"] == "Bodrum"
    hit = result["results"][0]
    assert hit["match"] == "place"
    assert hit["name"] == "Bodrum"
    assert hit["country"] == "TR"
    assert hit["display"]  # formatted coordinate present


def test_search_is_accent_and_case_insensitive():
    # "Kuşadası" normalises to "kusadasi"; a plain ASCII query must still match.
    result = search_places("kusadasi", _Settings())
    names = [r["name"] for r in result["results"]]
    assert "Kuşadası" in names


def test_search_exact_ranks_before_partial():
    result = search_places("Rodos", _Settings())
    assert result["results"][0]["name"] == "Rodos"
    assert result["results"][0]["match"] == "place"


def test_search_coordinate_query_leads_with_coordinate_hit():
    result = search_places("36.85, 28.27", _Settings())
    assert result["results"][0]["match"] == "coordinate"
    assert result["results"][0]["latitude"] == pytest.approx(36.85)


def test_search_blank_returns_empty():
    result = search_places("   ", _Settings())
    assert result["results"] == []
    assert result["persistence"] == MAP_INTERACTION_PERSISTENCE


def test_search_unknown_returns_empty():
    assert search_places("zzzznotaplacexx", _Settings())["results"] == []


def test_search_respects_max_results():
    result = search_places("a", _Settings(search_max=2))
    assert len(result["results"]) <= 2
    assert result["max_results"] == 2


def test_search_dms_format_display():
    result = search_places("Marmaris", _Settings(coord_format="dms"))
    assert "°" in result["results"][0]["display"]


# ------------------------------------------------------------- measure ----


def test_measure_distance_one_degree_meridian():
    # 1 degree along a meridian ~ 111.19 km on the mean sphere.
    result = measure_distance([[0.0, 0.0], [1.0, 0.0]], _Settings())
    assert result["mode"] == "distance"
    assert len(result["segments"]) == 1
    assert result["distance_km"] == pytest.approx(111.195, abs=0.5)


def test_measure_distance_adds_up():
    two = measure_distance([[37.0, 27.0], [37.1, 27.0]], _Settings())
    three = measure_distance([[37.0, 27.0], [37.1, 27.0], [37.2, 27.0]], _Settings())
    assert three["distance_km"] > two["distance_km"]


def test_measure_area_unit_box():
    box = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0]]
    result = measure_area(box, _Settings())
    assert result["mode"] == "area"
    assert result["area_km2"] == pytest.approx(12360, abs=200)
    assert result["area_ha"] == pytest.approx(result["area_km2"] * 100.0, abs=3)


def test_measure_area_auto_closes_ring():
    triangle = [[37.0, 27.0], [37.0, 27.1], [37.1, 27.0]]
    result = measure_area(triangle, _Settings())
    assert result["area_ha"] > 0.0
    assert result["points"] == [[p[0], p[1]] for p in triangle]


@pytest.mark.parametrize(
    "points",
    [
        [[0.0, 0.0]],  # too few for distance
        [],
        [[91.0, 0.0], [0.0, 0.0]],  # out of range lat
        [[0.0, 0.0], [0.0, 191.0]],  # out of range lon
        "not-a-list",
        [[0.0]],  # malformed point
    ],
)
def test_measure_distance_rejects_bad_input(points):
    with pytest.raises(MapInteractionError):
        measure_distance(points, _Settings())


def test_measure_area_needs_three_points():
    with pytest.raises(MapInteractionError):
        measure_area([[0.0, 0.0], [1.0, 1.0]], _Settings())


def test_measure_respects_max_points():
    pts = [[float(i % 80), float(i % 170)] for i in range(6)]
    with pytest.raises(MapInteractionError):
        measure_distance(pts, _Settings(max_points=4))


# --------------------------------------------------------------- config ----


def test_config_shape():
    cfg = map_interaction_config(_Settings())
    assert cfg["panel"] == "map_interaction"
    assert [b["key"] for b in cfg["basemaps"]] == list(BASEMAP_KEYS)
    assert cfg["default_basemap"] == "street"
    assert cfg["gazetteer_size"] == len(GAZETTEER)
    assert cfg["search_max_results"] == 8
    assert cfg["measure"]["min_distance_points"] == 2
    assert cfg["measure"]["min_area_points"] == 3
    assert cfg["measure"]["max_points"] == 100
    assert cfg["attribution"] == MAP_INTERACTION_ATTRIBUTION
    assert cfg["persistence"] == MAP_INTERACTION_PERSISTENCE


def test_config_falls_back_on_invalid_default_basemap():
    cfg = map_interaction_config(_Settings(default_basemap="bogus"))
    assert cfg["default_basemap"] == DEFAULT_BASEMAP


# ------------------------------------------------------------------ api ----


def test_http_map_config(client):
    response = client.get("/api/v1/map/config")
    assert response.status_code == 200
    body = response.json()
    assert len(body["basemaps"]) == 3
    assert body["default_basemap"] == "street"


def test_http_search_place_and_coordinate(client):
    place = client.get("/api/v1/map/search?q=Bodrum")
    assert place.status_code == 200
    assert place.json()["results"][0]["match"] == "place"
    coord = client.get("/api/v1/map/search?q=37.03, 27.43")
    assert coord.status_code == 200
    assert coord.json()["results"][0]["match"] == "coordinate"


def test_http_search_blank_is_empty(client):
    response = client.get("/api/v1/map/search?q=")
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_http_measure_distance_ok(client):
    response = client.post(
        "/api/v1/map/measure/distance",
        json={"points": [[0.0, 0.0], [1.0, 0.0]]},
    )
    assert response.status_code == 200
    assert response.json()["distance_km"] == pytest.approx(111.195, abs=0.5)


def test_http_measure_distance_bad_input_422(client):
    response = client.post(
        "/api/v1/map/measure/distance",
        json={"points": [[0.0, 0.0]]},
    )
    assert response.status_code == 422


def test_http_measure_area_ok(client):
    response = client.post(
        "/api/v1/map/measure/area",
        json={"points": [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0]]},
    )
    assert response.status_code == 200
    assert response.json()["area_km2"] == pytest.approx(12360, abs=200)


def test_openapi_publishes_map_paths(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/v1/map/config" in paths
    assert "/api/v1/map/search" in paths
    assert "/api/v1/map/measure/distance" in paths
    assert "/api/v1/map/measure/area" in paths
