"""EM-052 proactive resource positioning service, layer and endpoint tests."""
from datetime import datetime, timezone

import pytest

from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase
from src.models.spatial import FireEvent
from src.services.map_layers import build_layer
from src.services.positioning import (
    PositioningError,
    build_proposals,
    positioning_layer,
)
from src.services.road_network import (
    NormalizedSegment,
    RoadNetworkError,
    upsert_segments,
)

# Diamond topology (fast branch A-B-D, slow branch A-C-D) plus a disconnected
# island (nodes 10-11) used to exercise the unreachable-resource path.
NODE_A = (38.0, 27.0)
NODE_B = (38.0, 27.01)
NODE_C = (38.01, 27.0)
NODE_D = (38.01, 27.01)
ISLAND_1 = (38.5, 27.5)
ISLAND_2 = (38.51, 27.51)


def _seg(key, way, a_id, a, b_id, b, length, speed, highway="primary"):
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
        one_way=False,
    )


def _network():
    return [
        _seg("s1", 100, 1, NODE_A, 2, NODE_B, 1.0, 100.0),
        _seg("s2", 101, 2, NODE_B, 4, NODE_D, 1.0, 100.0),
        _seg("s3", 102, 1, NODE_A, 3, NODE_C, 1.0, 30.0, "residential"),
        _seg("s4", 103, 3, NODE_C, 4, NODE_D, 1.0, 30.0, "residential"),
        _seg("s5", 104, 10, ISLAND_1, 11, ISLAND_2, 1.0, 100.0),
    ]


def _event(session, key="EVT-1", coord=NODE_D):
    lat, lon = coord
    session.add(
        FireEvent(
            event_key=key,
            name="Test Fire",
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.01,
            max_lat=lat + 0.01,
            min_lon=lon - 0.01,
            max_lon=lon + 0.01,
            geometry_wkt=f"POINT({lon} {lat})",
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            source="manual",
        )
    )


def _base(session, key, coord, available=True):
    session.add(
        CrewBase(
            base_key=key,
            name=key.title(),
            latitude=coord[0],
            longitude=coord[1],
            crew_type="first_response",
            available=available,
        )
    )


def _asset(session, key, coord, rtype="helicopter", status="available"):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key.title(),
            resource_type=rtype,
            latitude=coord[0],
            longitude=coord[1],
            status=status,
            capacity=10.0,
        )
    )


# ------------------------------------------------------------- service ---


def test_build_proposals_ranks_by_eta_and_builds_route(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _base(session, "slow", NODE_C)
    _event(session)
    session.flush()

    proposals = build_proposals(session, None, "EVT-1")
    assert [p["resource_key"] for p in proposals] == ["fast", "slow"]
    assert proposals[0]["eta_minutes"] < proposals[1]["eta_minutes"]
    top = proposals[0]
    assert top["reachable"] is True
    assert top["deployment_point"] == {"latitude": NODE_D[0], "longitude": NODE_D[1]}
    geom = top["route"]["geometry"]
    assert geom["type"] == "LineString"
    # Route starts at the resource and ends at the fire location.
    assert geom["coordinates"][0] == [NODE_A[1], NODE_A[0]]
    assert geom["coordinates"][-1] == [NODE_D[1], NODE_D[0]]


def test_build_proposals_includes_suppression_resources(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _asset(session, "heli1", NODE_B, rtype="helicopter")
    _event(session)
    session.flush()

    proposals = build_proposals(session, None, "EVT-1")
    kinds = {p["kind"] for p in proposals}
    assert kinds == {"crew_base", "suppression_resource"}
    heli = next(p for p in proposals if p["kind"] == "suppression_resource")
    assert heli["resource_type"] == "helicopter"


def test_build_proposals_unreachable_last_and_limit(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _base(session, "island", ISLAND_1)  # disconnected from the fire
    _event(session)
    session.flush()

    proposals = build_proposals(session, None, "EVT-1")
    assert proposals[-1]["resource_key"] == "island"
    assert proposals[-1]["reachable"] is False
    assert proposals[-1]["eta_minutes"] is None
    assert proposals[-1]["route"]["geometry"]["coordinates"] == []

    capped = build_proposals(session, None, "EVT-1", limit=1)
    assert len(capped) == 1
    assert capped[0]["resource_key"] == "fast"


def test_build_proposals_unknown_event_raises(session):
    upsert_segments(session, _network())
    with pytest.raises(PositioningError):
        build_proposals(session, None, "NOPE")


def test_build_proposals_requires_event_key(session):
    with pytest.raises(PositioningError):
        build_proposals(session, None, None)


def test_build_proposals_empty_network_raises(session):
    _event(session)
    _base(session, "fast", NODE_A)
    session.flush()
    with pytest.raises(RoadNetworkError):
        build_proposals(session, None, "EVT-1")


# ---------------------------------------------------------------- layer ---


def test_positioning_layer_emits_points_and_lines(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _base(session, "island", ISLAND_1)
    _event(session)
    session.flush()

    layer = positioning_layer(session, None, "EVT-1")
    assert layer["type"] == "FeatureCollection"
    assert layer["layer"] == "positioning"
    kinds = [f["properties"]["kind"] for f in layer["features"]]
    # Only the reachable proposal is drawn: one point + one line.
    assert kinds == ["deployment_point", "positioning_route"]
    assert layer["attribution"]


def test_positioning_layer_empty_for_unknown_event(session):
    upsert_segments(session, _network())
    layer = positioning_layer(session, None, "MISSING")
    assert layer["count"] == 0
    assert layer["features"] == []


def test_build_layer_dispatches_positioning(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _event(session)
    session.flush()
    layer = build_layer(session, None, "positioning", event_key="EVT-1")
    assert layer["count"] == 2


# ----------------------------------------------------------- endpoint ---


def test_positioning_endpoint_lists_proposals(client, session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _event(session)
    session.commit()

    response = client.get("/api/v1/positioning/proposals?event_key=EVT-1")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["event_key"] == "EVT-1"
    assert body["attribution"]
    proposal = body["proposals"][0]
    assert proposal["resource_key"] == "fast"
    assert proposal["eta_minutes"] is not None


def test_positioning_endpoint_unknown_event_404(client, session):
    upsert_segments(session, _network())
    session.commit()
    response = client.get("/api/v1/positioning/proposals?event_key=NOPE")
    assert response.status_code == 404


def test_positioning_endpoint_requires_event_key(client):
    response = client.get("/api/v1/positioning/proposals")
    assert response.status_code == 422
