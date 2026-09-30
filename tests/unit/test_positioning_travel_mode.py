"""EM-049 type-aware ETA: aerial assets fly great-circle, ground crews road-route.

Positioning already ranked resources by closure-aware road ETA (EM-052). EM-049
adds the travel *mode*: helicopters/UAVs reach the incident over the air at a
cruise speed (great-circle distance), independent of the road graph and any
closures, while ground crews keep the road routing. These tests pin that split.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase
from src.models.spatial import FireEvent
from src.services.positioning import build_proposals, haversine_km, positioning_layer
from src.services.road_network import (
    NormalizedSegment,
    RoadClosure,
    upsert_segments,
)

NODE_A = (38.0, 27.0)
NODE_B = (38.0, 27.01)
NODE_D = (38.01, 27.01)
ISLAND_1 = (38.5, 27.5)
ISLAND_2 = (38.51, 27.51)

_SETTINGS = SimpleNamespace(
    POSITIONING_MAX_PROPOSALS=5, POSITIONING_AIR_SPEED_KMH=220.0
)


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


def _base(session, key, coord):
    session.add(
        CrewBase(
            base_key=key,
            name=key.title(),
            latitude=coord[0],
            longitude=coord[1],
            crew_type="first_response",
            available=True,
        )
    )


def _asset(session, key, coord, rtype="helicopter"):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key.title(),
            resource_type=rtype,
            latitude=coord[0],
            longitude=coord[1],
            status="available",
            capacity=10.0,
        )
    )


# ------------------------------------------------------------- service ---


def test_crew_base_uses_road_mode(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _event(session)
    session.flush()

    proposal = build_proposals(session, _SETTINGS, "EVT-1")[0]
    assert proposal["travel_mode"] == "road"
    # Road distance chains the segments, so it exceeds the straight-line distance.
    straight = haversine_km(*NODE_A, *NODE_D)
    assert proposal["distance_km"] > straight


def test_helicopter_uses_air_mode_and_straight_line(session):
    upsert_segments(session, _network())
    _asset(session, "heli1", NODE_B, rtype="helicopter")
    _event(session)
    session.flush()

    proposal = build_proposals(session, _SETTINGS, "EVT-1")[0]
    assert proposal["travel_mode"] == "air"
    assert proposal["reachable"] is True
    straight_km = haversine_km(*NODE_B, *NODE_D)
    assert proposal["distance_km"] == round(straight_km, 3)
    expected_eta = round(straight_km / 220.0 * 60.0, 2)
    assert proposal["eta_minutes"] == expected_eta
    # The flight path is a two-point straight line origin -> destination.
    coords = proposal["route"]["geometry"]["coordinates"]
    assert coords == [[NODE_B[1], NODE_B[0]], [NODE_D[1], NODE_D[0]]]


def test_uav_is_airborne_too(session):
    upsert_segments(session, _network())
    _asset(session, "uav1", NODE_B, rtype="uav")
    _event(session)
    session.flush()

    proposal = build_proposals(session, _SETTINGS, "EVT-1")[0]
    assert proposal["travel_mode"] == "air"


def test_air_reaches_disconnected_island(session):
    upsert_segments(session, _network())
    _base(session, "island_crew", ISLAND_1)  # road-isolated -> unreachable
    _asset(session, "heli_island", ISLAND_1, rtype="helicopter")  # flies -> reachable
    _event(session)
    session.flush()

    proposals = build_proposals(session, _SETTINGS, "EVT-1")
    heli = next(p for p in proposals if p["resource_key"] == "heli_island")
    crew = next(p for p in proposals if p["resource_key"] == "island_crew")
    assert heli["travel_mode"] == "air" and heli["reachable"] is True
    assert crew["travel_mode"] == "road" and crew["reachable"] is False
    # Aerial unit outranks the road-blocked crew despite equal start position.
    assert proposals.index(heli) < proposals.index(crew)


def test_closures_do_not_delay_aerial_units(session):
    upsert_segments(session, _network())
    _asset(session, "heli1", NODE_B, rtype="helicopter")
    _event(session)
    session.add(
        RoadClosure(
            segment_key="s2",
            reason="test closure",
            status="active",
            reported_at=datetime(2025, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
        )
    )
    session.flush()

    proposal = build_proposals(session, _SETTINGS, "EVT-1")[0]
    assert proposal["travel_mode"] == "air"
    assert proposal["delay_vs_open_minutes"] == 0.0


def test_higher_air_speed_yields_lower_eta(session):
    upsert_segments(session, _network())
    _asset(session, "heli1", NODE_B, rtype="helicopter")
    _event(session)
    session.flush()

    straight = haversine_km(*NODE_B, *NODE_D)
    slow = build_proposals(
        session, SimpleNamespace(POSITIONING_AIR_SPEED_KMH=110.0), "EVT-1"
    )[0]
    fast = build_proposals(
        session, SimpleNamespace(POSITIONING_AIR_SPEED_KMH=440.0), "EVT-1"
    )[0]
    assert slow["eta_minutes"] == round(straight / 110.0 * 60.0, 2)
    assert fast["eta_minutes"] == round(straight / 440.0 * 60.0, 2)
    assert fast["eta_minutes"] < slow["eta_minutes"]


# ---------------------------------------------------------------- layer ---


def test_layer_exposes_travel_mode(session):
    upsert_segments(session, _network())
    _asset(session, "heli1", NODE_B, rtype="helicopter")
    _base(session, "fast", NODE_A)
    _event(session)
    session.flush()

    layer = positioning_layer(session, _SETTINGS, "EVT-1")
    points = [
        f for f in layer["features"] if f["properties"]["kind"] == "deployment_point"
    ]
    modes = {
        p["properties"]["resource_key"]: p["properties"]["travel_mode"] for p in points
    }
    assert modes["heli1"] == "air"
    assert modes["fast"] == "road"


# ----------------------------------------------------------- endpoint ---


def test_endpoint_returns_travel_mode(client, session):
    upsert_segments(session, _network())
    _asset(session, "heli1", NODE_B, rtype="helicopter")
    _event(session)
    session.commit()

    response = client.get("/api/v1/positioning/proposals?event_key=EVT-1")
    assert response.status_code == 200
    body = response.json()
    assert body["proposals"][0]["travel_mode"] == "air"


# ------------------------------------------------------------------ ui ---


def test_ui_renders_travel_mode_badge():
    from pathlib import Path

    html = Path("src/static/operator_map.html").read_text(encoding="utf-8")
    assert "mode-air" in html
    assert "mode-road" in html
    assert "Hava (kuş uçuşu)" in html
    assert "travel_mode" in html
