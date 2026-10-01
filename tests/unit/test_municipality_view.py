"""EM-083 read-only municipality monitoring view tests (Epic E8).

The view is a read-time projection that scopes the survey to a configurable
region bounding box (defaults to the pilot region) and returns only simplified,
monitoring-only essentials: active fires inside the box (most-severe first), a
severity histogram, a single headline status and a local-vs-pool capacity
snapshot. Operator-only decision controls are intentionally absent. These tests
pin the box filtering (inclusive boundary), the active-only + severity ordering,
the local/pool capacity split, the severity filter contract (headline stays
region-wide, unknown band not silently dropped), the ``max_fires`` bound, the
region-box override path and the read-only HTTP endpoints.
"""
from datetime import timedelta

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent
from src.services.municipality_view import (
    MUNICIPALITY_VIEW_ATTRIBUTION,
    MUNICIPALITY_VIEW_PERSISTENCE,
    MUNICIPALITY_VIEW_READ_ONLY,
    OMITTED_OPERATOR_CONTROLS,
    municipality_view,
    municipality_view_config,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Region box + fire cap. Defaults mirror the pilot-region fallbacks."""

    def __init__(
        self,
        *,
        min_lat=36.0,
        max_lat=39.5,
        min_lon=26.0,
        max_lon=30.0,
        max_fires=100,
        name="TR-GR Coastal Wildfire Pilot Region",
    ):
        self.MUNICIPALITY_VIEW_MIN_LAT = min_lat
        self.MUNICIPALITY_VIEW_MAX_LAT = max_lat
        self.MUNICIPALITY_VIEW_MIN_LON = min_lon
        self.MUNICIPALITY_VIEW_MAX_LON = max_lon
        self.MUNICIPALITY_VIEW_MAX_FIRES = max_fires
        self.MUNICIPALITY_VIEW_REGION_NAME = name


def _fire(
    session,
    key,
    *,
    severity="medium",
    status="active",
    lat=37.75,
    lon=28.0,
    minutes_ago=0,
):
    now = utc_now()
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} yangını",
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.05,
            max_lat=lat + 0.05,
            min_lon=lon - 0.05,
            max_lon=lon + 0.05,
            geometry_wkt=f"POINT({lat} {lon})",
            severity=severity,
            status=status,
            started_at=now - timedelta(minutes=minutes_ago),
        )
    )


def _unit(session, key, *, status="available", lat=37.75, lon=28.0):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=f"{key} birimi",
            resource_type="crew",
            latitude=lat,
            longitude=lon,
            status=status,
        )
    )


def test_only_active_fires_inside_box_are_listed(session):
    _fire(session, "in-1")
    _fire(session, "contained", status="contained")
    _fire(session, "out", lat=41.0)  # above max_lat
    session.flush()
    data = municipality_view(session, _Settings())
    keys = [f["event_key"] for f in data["fires"]]
    assert keys == ["in-1"]
    assert data["fire_count"] == 1
    assert data["active_fire_total"] == 1


def test_boundary_is_inclusive(session):
    _fire(session, "corner", lat=39.5, lon=30.0)
    session.flush()
    data = municipality_view(session, _Settings())
    assert [f["event_key"] for f in data["fires"]] == ["corner"]


def test_fires_ordered_most_severe_first(session):
    _fire(session, "low", severity="low")
    _fire(session, "crit", severity="critical")
    _fire(session, "med", severity="medium")
    session.flush()
    data = municipality_view(session, _Settings())
    keys = [f["event_key"] for f in data["fires"]]
    assert keys == ["crit", "med", "low"]
    assert data["headline"]["most_severe"] == "critical"


def test_severity_counts_and_headline(session):
    _fire(session, "a", severity="high")
    _fire(session, "b", severity="medium")
    _fire(session, "c", severity="high")
    session.flush()
    data = municipality_view(session, _Settings())
    assert data["severity_counts"] == {
        "critical": 0,
        "high": 2,
        "medium": 1,
        "low": 0,
    }
    assert data["headline"]["most_severe"] == "high"
    assert data["headline"]["status"] == "aktif yangın var"


def test_local_vs_pool_capacity_split(session):
    _unit(session, "local-free", status="available")
    _unit(session, "local-busy", status="deployed")
    _unit(session, "pool-free", status="available", lat=41.0)
    _unit(session, "maintenance", status="maintenance")  # neither bucket
    session.flush()
    data = municipality_view(session, _Settings())
    cap = data["capacity"]
    assert cap["local_available_units"] == 1
    assert cap["local_committed_units"] == 1
    assert cap["pool_available_units"] == 2
    assert cap["pool_committed_units"] == 1


def test_empty_region_is_calm(session):
    _fire(session, "far", lat=41.0, lon=28.0)
    session.flush()
    data = municipality_view(session, _Settings())
    assert data["fires"] == []
    assert data["headline"]["active_fire_count"] == 0
    assert data["headline"]["most_severe"] is None
    assert data["headline"]["status"] == "bölgede aktif yangın yok"


def test_severity_filter_keeps_headline_region_wide(session):
    _fire(session, "h", severity="high")
    _fire(session, "l", severity="low")
    session.flush()
    data = municipality_view(session, _Settings(), severity="low")
    assert [f["event_key"] for f in data["fires"]] == ["l"]
    assert data["fire_count"] == 1
    # headline / severity_counts stay region-wide (nothing serious is hidden)
    assert data["active_fire_total"] == 2
    assert data["headline"]["most_severe"] == "high"
    assert data["severity_counts"]["high"] == 1


def test_severity_filter_is_case_insensitive(session):
    _fire(session, "h", severity="high")
    session.flush()
    data = municipality_view(session, _Settings(), severity=" HIGH ")
    assert [f["event_key"] for f in data["fires"]] == ["h"]
    assert data["filter"]["severity"] == "high"


def test_unknown_severity_filter_is_not_applied_silently(session):
    _fire(session, "h", severity="high")
    _fire(session, "l", severity="low")
    session.flush()
    data = municipality_view(session, _Settings(), severity="bogus")
    # nothing recognised -> no filtering, both fires still listed
    assert data["fire_count"] == 2
    assert data["filter"]["severity"] is None
    assert data["filter"]["requested_severity"] == "bogus"
    assert data["filter"]["severity_recognised"] is False


def test_max_fires_bounds_the_list(session):
    for i in range(5):
        _fire(session, f"f{i}", severity="low", minutes_ago=i)
    session.flush()
    data = municipality_view(session, _Settings(max_fires=2))
    assert data["fire_count"] == 2
    assert data["active_fire_total"] == 5
    assert data["max_fires"] == 2


def test_region_box_override_narrows_scope(session):
    _fire(session, "in", lat=37.0, lon=27.0)
    _fire(session, "out", lat=38.9, lon=29.9)
    session.flush()
    tight = _Settings(min_lat=36.5, max_lat=37.5, min_lon=26.5, max_lon=27.5)
    data = municipality_view(session, tight)
    assert [f["event_key"] for f in data["fires"]] == ["in"]
    assert data["region"]["name"] == tight.MUNICIPALITY_VIEW_REGION_NAME


def test_metadata_is_read_only(session):
    session.flush()
    data = municipality_view(session, _Settings())
    assert data["panel"] == "municipality_view"
    assert data["read_only"] is MUNICIPALITY_VIEW_READ_ONLY is True
    assert data["persistence"] == MUNICIPALITY_VIEW_PERSISTENCE == "none"
    assert data["attribution"] == MUNICIPALITY_VIEW_ATTRIBUTION


def test_config_payload(session):
    cfg = municipality_view_config(_Settings())
    assert cfg["panel"] == "municipality_view"
    assert cfg["read_only"] is True
    assert cfg["severities"] == ["critical", "high", "medium", "low"]
    assert cfg["omitted_operator_controls"] == list(OMITTED_OPERATOR_CONTROLS)
    assert len(cfg["sources"]) == 2
    assert cfg["region"]["min_lat"] == 36.0
    assert cfg["persistence"] == "none"


def test_endpoint_returns_view(api, client, session):
    _fire(session, "e1", severity="high")
    session.commit()
    resp = client.get("/api/v1/municipality-view")
    assert resp.status_code == 200
    body = resp.json()
    assert body["headline"]["active_fire_count"] == 1
    assert body["fires"][0]["event_key"] == "e1"


def test_endpoint_severity_query(api, client, session):
    _fire(session, "h", severity="high")
    _fire(session, "l", severity="low")
    session.commit()
    resp = client.get("/api/v1/municipality-view", params={"severity": "low"})
    assert resp.status_code == 200
    body = resp.json()
    assert [f["event_key"] for f in body["fires"]] == ["l"]


def test_endpoint_config(api, client):
    resp = client.get("/api/v1/municipality-view/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["read_only"] is True
    assert body["omitted_operator_controls"] == list(OMITTED_OPERATOR_CONTROLS)
