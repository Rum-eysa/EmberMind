"""EM-046 explainable recommendation tests.

Covers the "why?" service (recommended proposals carry a rationale, rejected
alternatives each carry a loss reason, and the shared decision context exposes
the metric / evaluated-count / threshold), the HTTP endpoints, and the
operator_map.html integration that renders a per-proposal explanation panel.
"""
from datetime import datetime, timezone

import pytest

from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase
from src.models.spatial import FireEvent
from src.services.positioning import PositioningError
from src.services.recommendation_explain import explain_proposals
from src.services.road_network import (
    NormalizedSegment,
    RoadNetworkError,
    upsert_segments,
)

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


def _seed(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)  # near, via fast roads
    _base(session, "slow", NODE_C)  # near, via slow residential
    _base(session, "island", ISLAND_1)  # unreachable
    _event(session)
    session.flush()


# --- service ---------------------------------------------------------------
def test_explain_annotates_recommended_with_reasons(session):
    _seed(session)
    res = explain_proposals(session, None, "EVT-1", limit=1)
    assert res["count"] == 1
    top = res["proposals"][0]
    assert top["rank"] == 1
    assert top["resource_key"] == "fast"
    assert isinstance(top["why"], list) and top["why"]
    assert any("En kısa tahmini varış" in w for w in top["why"])


def test_explain_surfaces_rejected_alternatives(session):
    _seed(session)
    res = explain_proposals(session, None, "EVT-1", limit=1)
    rejected = {a["resource_key"]: a["reason"] for a in res["rejected_alternatives"]}
    # slow loses on ETA; island loses on unreachability.
    assert "slow" in rejected and "Daha uzun tahmini varış" in rejected["slow"]
    assert "island" in rejected and "ulaşılamıyor" in rejected["island"]
    assert res["rejected_count"] == len(res["rejected_alternatives"])


def test_explain_context_reports_metric_and_threshold(session):
    _seed(session)
    res = explain_proposals(session, None, "EVT-1", limit=1)
    ctx = res["context"]
    assert ctx["ranking_metric"]
    assert ctx["alternatives_evaluated"] == 3  # fast, slow, island
    assert ctx["selected_limit"] == 1
    assert ctx["threshold_eta_minutes"] == res["proposals"][0]["eta_minutes"]


def test_explain_no_rejected_when_all_fit(session):
    _seed(session)
    res = explain_proposals(session, None, "EVT-1", limit=10)
    assert res["rejected_alternatives"] == []
    assert res["count"] == 3


def test_explain_unknown_event_raises(session):
    _seed(session)
    with pytest.raises(PositioningError):
        explain_proposals(session, None, "NOPE")


def test_explain_empty_network_raises(session):
    _event(session)
    session.flush()
    with pytest.raises(RoadNetworkError):
        explain_proposals(session, None, "EVT-1")


# --- HTTP endpoints --------------------------------------------------------
def test_explain_endpoint(client, session):
    _seed(session)
    session.commit()
    res = client.get("/api/v1/recommendations/explain?event_key=EVT-1&limit=1")
    assert res.status_code == 200
    body = res.json()
    assert body["proposals"][0]["why"]
    assert body["rejected_alternatives"]
    assert body["context"]["alternatives_evaluated"] == 3


def test_explain_endpoint_unknown_event_404(client, session):
    _seed(session)
    session.commit()
    assert (
        client.get("/api/v1/recommendations/explain?event_key=NOPE").status_code == 404
    )


def test_explain_endpoint_requires_event_key(client):
    assert client.get("/api/v1/recommendations/explain").status_code == 422


def test_explain_endpoint_config(client):
    body = client.get("/api/v1/recommendations/explain/config").json()
    assert body["shows_rejected_alternatives"] is True
    assert body["ranking_metric"]
    assert body["selected_limit_default"] >= 1


# --- UI integration --------------------------------------------------------
def test_operator_map_has_explain_panel():
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[2] / "src" / "static" / "operator_map.html"
    ).read_text(encoding="utf-8")
    assert "db-why" in html
    assert "explainProposal(" in html
    assert "/api/v1/recommendations/explain" in html
