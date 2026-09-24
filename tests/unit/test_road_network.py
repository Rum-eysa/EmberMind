"""OpenStreetMap road-network import, routing, ETA and closure re-routing unit tests."""
from datetime import datetime, timezone

from sqlalchemy import select

from src.models.road_network import CrewBase, RoadClosure, RoadSegment
from src.services.road_network import (
    NormalizedSegment,
    RoadSegmentNotFoundError,
    compute_arrival_for_event,
    compute_crew_arrival,
    haversine_km,
    mark_road_closure,
    parse_overpass_response,
    resolve_road_closure,
    speed_for_highway,
    sync_road_network,
    upsert_segments,
)

# Diamond topology: node1 (A) -> node4 (D) via a fast branch (node2) and a slow branch (node3).
NODE_A = (38.0, 27.0)
NODE_B = (38.0, 27.01)
NODE_C = (38.01, 27.0)
NODE_D = (38.01, 27.01)


def _seg(key, way, a_id, a, b_id, b, length, speed, highway="primary", one_way=False):
    return NormalizedSegment(
        segment_key=key,
        osm_way_id=way,
        from_node_id=a_id,
        to_node_id=b_id,
        from_lat=a[0],
        from_lon=a[1],
        to_lat=b[0],
        to_lon=b[1],
        highway=highway,
        name=None,
        length_km=length,
        max_speed_kmh=speed,
        one_way=one_way,
    )


def _diamond_segments():
    return [
        _seg("s1", 100, 1, NODE_A, 2, NODE_B, 1.0, 100.0),  # fast branch A->B
        _seg("s2", 101, 2, NODE_B, 4, NODE_D, 1.0, 100.0),  # fast branch B->D
        _seg("s3", 102, 1, NODE_A, 3, NODE_C, 1.0, 30.0, "residential"),  # slow A->C
        _seg("s4", 103, 3, NODE_C, 4, NODE_D, 1.0, 30.0, "residential"),  # slow C->D
    ]


def test_haversine_km_basic():
    assert haversine_km(38.0, 27.0, 38.0, 27.0) == 0.0
    # ~111 km per degree of latitude.
    assert 110.0 < haversine_km(38.0, 27.0, 39.0, 27.0) < 112.0


def test_speed_for_highway_mapping():
    assert speed_for_highway("primary") == 90.0
    assert speed_for_highway("MOTORWAY") == 130.0
    assert speed_for_highway("unknown_class") == 50.0


def test_parse_overpass_response_builds_links():
    payload = {
        "elements": [
            {"type": "node", "id": 11, "lat": 38.0, "lon": 27.0},
            {"type": "node", "id": 12, "lat": 38.0, "lon": 27.001},
            {"type": "node", "id": 13, "lat": 38.0, "lon": 27.002},
            {
                "type": "way",
                "id": 100,
                "nodes": [11, 12, 13],
                "tags": {"highway": "primary", "name": "Test Cd", "maxspeed": "90"},
            },
        ]
    }
    segments = parse_overpass_response(payload)
    assert len(segments) == 2
    assert segments[0].segment_key == "way100_link0"
    assert segments[0].max_speed_kmh == 90.0
    assert segments[0].highway == "primary"
    assert segments[0].name == "Test Cd"
    assert all(s.length_km > 0 for s in segments)


def test_parse_overpass_skips_pedestrian_and_marks_oneway():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 38.0, "lon": 27.0},
            {"type": "node", "id": 2, "lat": 38.0, "lon": 27.001},
            {
                "type": "way",
                "id": 50,
                "nodes": [1, 2],
                "tags": {"highway": "footway"},
            },
            {
                "type": "way",
                "id": 60,
                "nodes": [1, 2],
                "tags": {"highway": "secondary", "oneway": "yes"},
            },
        ]
    }
    segments = parse_overpass_response(payload)
    assert len(segments) == 1
    assert segments[0].osm_way_id == 60
    assert segments[0].one_way is True


def test_sync_road_network_persists_and_upserts(session):
    class FakeClient:
        def fetch_network(self, bbox):  # noqa: ANN001, ARG002
            return _diamond_segments()

    result = sync_road_network(
        session, object(), (36.0, 26.0, 39.0, 30.0), FakeClient()
    )
    assert result["segments_fetched"] == 4
    assert result["segments_saved"] == 4

    rows = session.scalars(select(RoadSegment)).all()
    assert len(rows) == 4

    # Re-running must upsert (no duplicates created).
    sync_road_network(session, object(), (36.0, 26.0, 39.0, 30.0), FakeClient())
    rows_after = session.scalars(select(RoadSegment)).all()
    assert len(rows_after) == 4


def test_compute_crew_arrival_prefers_fast_route(session):
    upsert_segments(session, _diamond_segments())
    route = compute_crew_arrival(session, NODE_A, NODE_D)
    assert route.reachable is True
    assert route.path_segment_keys == ["s1", "s2"]
    assert route.closures_avoided == 0
    assert route.delay_vs_open_minutes == 0.0


def test_closure_forces_recompute(session):
    upsert_segments(session, _diamond_segments())
    baseline = compute_crew_arrival(session, NODE_A, NODE_D)

    mark_road_closure(session, "s1", reason="fire spread")
    rerouted = compute_crew_arrival(session, NODE_A, NODE_D)

    assert rerouted.reachable is True
    assert "s1" not in rerouted.path_segment_keys
    assert rerouted.path_segment_keys == ["s3", "s4"]
    assert rerouted.eta_minutes > baseline.eta_minutes
    assert rerouted.delay_vs_open_minutes > 0.0
    assert rerouted.closures_avoided == 1


def test_resolve_closure_restores_fast_route(session):
    upsert_segments(session, _diamond_segments())
    mark_road_closure(session, "s1")
    assert resolve_road_closure(session, "s1") == 1
    route = compute_crew_arrival(session, NODE_A, NODE_D)
    assert route.path_segment_keys == ["s1", "s2"]


def test_mark_closure_unknown_segment_raises(session):
    upsert_segments(session, _diamond_segments())
    try:
        mark_road_closure(session, "does-not-exist")
        raise AssertionError("expected RoadSegmentNotFoundError")
    except RoadSegmentNotFoundError:
        assert True


def test_compute_arrival_ranks_crew_bases(session):
    upsert_segments(session, _diamond_segments())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add_all(
        [
            CrewBase(
                base_key="fast_station",
                name="Fast",
                latitude=NODE_A[0],
                longitude=NODE_A[1],
                crew_type="first_response",
                available=True,
                created_at=now,
                updated_at=now,
            ),
            CrewBase(
                base_key="slow_station",
                name="Slow",
                latitude=NODE_C[0],
                longitude=NODE_C[1],
                crew_type="engine",
                available=True,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    session.flush()

    arrivals = compute_arrival_for_event(session, NODE_D)
    assert [a["base_key"] for a in arrivals] == ["fast_station", "slow_station"]
    assert arrivals[0]["eta_minutes"] < arrivals[1]["eta_minutes"]
    assert arrivals[0]["reachable"] is True


def test_closure_persisted_as_active(session):
    upsert_segments(session, _diamond_segments())
    mark_road_closure(session, "s2", reason="blocked bridge", reported_by="cmd-01")
    closures = session.scalars(select(RoadClosure)).all()
    assert len(closures) == 1
    assert closures[0].status == "active"
    assert closures[0].reason == "blocked bridge"


# --------------------------- API endpoint tests ---------------------------


def test_api_roads_empty_list(client):
    resp = client.get("/api/v1/roads")
    assert resp.status_code == 200
    assert resp.json()["source"] == "OpenStreetMap"
    assert resp.json()["count"] == 0


def test_api_crew_base_create_and_list(client, api):
    payload = {
        "base_key": "station_alpha",
        "name": "Alpha",
        "latitude": 38.0,
        "longitude": 27.0,
        "crew_type": "first_response",
        "available": True,
    }
    created = client.post("/api/v1/crew-bases", json=payload)
    assert created.status_code == 200
    assert created.json()["status"] == "created"

    duplicate = client.post("/api/v1/crew-bases", json=payload)
    assert duplicate.status_code == 409

    listed = client.get("/api/v1/crew-bases")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1


def test_api_routing_eta_requires_network(client):
    resp = client.post(
        "/api/v1/routing/eta",
        json={
            "origin_lat": 38.0,
            "origin_lon": 27.0,
            "dest_lat": 38.01,
            "dest_lon": 27.01,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["status"] == "no_network"


def test_api_closure_recompute_flow(client, api):
    with api.state.database.session() as session:
        upsert_segments(session, _diamond_segments())

    eta_open = client.post(
        "/api/v1/routing/eta",
        json={
            "origin_lat": NODE_A[0],
            "origin_lon": NODE_A[1],
            "dest_lat": NODE_D[0],
            "dest_lon": NODE_D[1],
        },
    )
    assert eta_open.status_code == 200
    assert eta_open.json()["route"]["path_segment_keys"] == ["s1", "s2"]

    close = client.post(
        "/api/v1/roads/closures",
        json={"segment_key": "s1", "reason": "evacuation"},
    )
    assert close.status_code == 200
    assert close.json()["closure"]["status"] == "active"

    eta_closed = client.post(
        "/api/v1/routing/eta",
        json={
            "origin_lat": NODE_A[0],
            "origin_lon": NODE_A[1],
            "dest_lat": NODE_D[0],
            "dest_lon": NODE_D[1],
        },
    )
    assert eta_closed.status_code == 200
    route = eta_closed.json()["route"]
    assert route["path_segment_keys"] == ["s3", "s4"]
    assert route["closures_avoided"] == 1
    assert route["delay_vs_open_minutes"] > 0

    reopen = client.delete("/api/v1/roads/closures/s1")
    assert reopen.status_code == 200
    assert reopen.json()["status"] == "resolved"


def test_api_closure_unknown_segment(client):
    resp = client.post(
        "/api/v1/roads/closures",
        json={"segment_key": "ghost", "reason": "x"},
    )
    assert resp.status_code == 404
