"""EM-048 recommendation impact comparison - applied vs not-applied risk.

The comparison reuses the EM-029 risk engine and the EM-052 positioning proposals:
"applied" secures the recommended suppression units for this incident (full
effective capacity), "not applied" holds them back (capacity reduced by their
summed ha/hour). These tests pin the capacity split, the side-by-side risk move,
the zero-value case and the HTTP surface.
"""
from datetime import datetime, timezone

import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.capacity_whatif import RiskIndexError  # re-exported type
from src.services.recommendation_impact import (
    IMPACT_PANEL,
    ImpactError,
    compare_impact,
)
from src.services.positioning import PositioningError
from src.services.road_network import (
    NormalizedSegment,
    RoadNetworkError,
    upsert_segments,
)

NODE_A = (38.0, 27.0)
NODE_B = (38.0, 27.01)
NODE_D = (38.01, 27.01)
ISLAND_1 = (38.5, 27.5)
ISLAND_2 = (38.51, 27.51)


class _Settings:
    """Risk thresholds + horizons; capacity keys omitted so type defaults apply
    (crew 2.0, helicopter 12.0, uav 4.0 ha/hour)."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


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


def _event(session, key="EVT-IMP", coord=NODE_D):
    lat, lon = coord
    session.add(
        FireEvent(
            event_key=key,
            name="Impact Fire",
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.05,
            max_lat=lat + 0.05,
            min_lon=lon - 0.05,
            max_lon=lon + 0.05,
            geometry_wkt=f"POINT({lon} {lat})",
            status="active",
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            source="manual",
        )
    )


def _asset(session, key, coord, rtype="crew", status="available"):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key,
            resource_type=rtype,
            latitude=coord[0],
            longitude=coord[1],
            status=status,
            capacity=1.0,
        )
    )


def _forecast(session, event, horizon, area_ha):
    session.add(
        FireForecast(
            event_key=event,
            model_name="rothermel_v1",
            latitude=NODE_D[0],
            longitude=NODE_D[1],
            predicted_area_ha=area_ha,
            geometry_wkt="POLYGON((27 38,27.01 38,27.01 38.01,27 38.01,27 38))",
            forecast_for=datetime(2025, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            horizon_minutes=horizon,
            rate_of_spread_m_per_min=10.0,
            spread_direction_deg=45.0,
            inputs_json="{}",
        )
    )


def _seed_two_crews(session):
    # One road-reachable crew (committed) + one road-isolated crew (available,
    # so counted in capacity but never recommended) + forecasts at all horizons.
    upsert_segments(session, _network())
    _event(session)
    _asset(session, "crew_near", NODE_A, rtype="crew")
    _asset(session, "crew_island", ISLAND_1, rtype="crew")
    for horizon, area in ((30, 2.0), (60, 3.0), (120, 4.0)):
        _forecast(session, "EVT-IMP", horizon, area)
    session.flush()


# ------------------------------------------------------------- service ---


def test_capacity_split_and_committed_units(session):
    _seed_two_crews(session)
    result = compare_impact(session, _Settings(), "EVT-IMP")

    assert result["panel"] == IMPACT_PANEL
    assert result["event_key"] == "EVT-IMP"
    cap = result["capacity"]
    assert cap["applied_ha_h"] == 4.0  # both available crews counted
    assert cap["committed_ha_h"] == 2.0  # only the reachable crew recommended
    assert cap["not_applied_ha_h"] == 2.0  # applied minus the committed unit
    assert [c["resource_key"] for c in result["committed_resources"]] == ["crew_near"]


def test_applying_reduces_risk_side_by_side(session):
    _seed_two_crews(session)
    result = compare_impact(session, _Settings(), "EVT-IMP")

    rows = result["side_by_side"]
    assert len(rows) == 3
    # Securing the recommended unit can only help: never worse, sometimes better.
    assert all(row["risk_index_delta"] is not None for row in rows)
    assert all(row["risk_index_delta"] <= 0 for row in rows)
    assert any(row["risk_index_delta"] < 0 for row in rows)
    assert result["summary"]["decision_has_value"] is True
    assert result["summary"]["horizons_risk_reduced"] >= 1


def test_no_recommended_units_yields_zero_value(session):
    upsert_segments(session, _network())
    _event(session)
    _asset(session, "crew_island", ISLAND_1, rtype="crew")  # never reachable
    _forecast(session, "EVT-IMP", 60, 3.0)
    session.flush()

    result = compare_impact(session, _Settings(), "EVT-IMP")
    assert result["capacity"]["committed_ha_h"] == 0.0
    assert result["capacity"]["not_applied_ha_h"] == result["capacity"]["applied_ha_h"]
    assert result["summary"]["decision_has_value"] is False
    assert all(row["risk_index_delta"] == 0 for row in result["side_by_side"])


def test_unknown_event_raises(session):
    upsert_segments(session, _network())
    with pytest.raises(PositioningError):
        compare_impact(session, _Settings(), "NOPE")


def test_empty_network_raises(session):
    _event(session)
    _asset(session, "crew_near", NODE_A, rtype="crew")
    session.flush()
    with pytest.raises(RoadNetworkError):
        compare_impact(session, _Settings(), "EVT-IMP")


def test_no_forecasts_raises_impact_error(session):
    upsert_segments(session, _network())
    _event(session)
    _asset(session, "crew_near", NODE_A, rtype="crew")
    session.flush()
    with pytest.raises(ImpactError):
        compare_impact(session, _Settings(), "EVT-IMP")


def test_risk_index_error_is_exposed_for_routes():
    # The route maps this to 404; import it so the alias stays covered.
    assert RiskIndexError is not None


# ----------------------------------------------------------- endpoint ---


def test_endpoint_returns_side_by_side(client, session):
    _seed_two_crews(session)
    session.commit()
    response = client.get("/api/v1/recommendations/impact?event_key=EVT-IMP")
    assert response.status_code == 200
    body = response.json()
    assert body["panel"] == IMPACT_PANEL
    assert "side_by_side" in body
    assert body["summary"]["decision_has_value"] is True


def test_endpoint_unknown_event_404(client, session):
    upsert_segments(session, _network())
    session.commit()
    response = client.get("/api/v1/recommendations/impact?event_key=NOPE")
    assert response.status_code == 404


def test_endpoint_requires_event_key(client):
    response = client.get("/api/v1/recommendations/impact")
    assert response.status_code == 422


def test_endpoint_config(client):
    response = client.get("/api/v1/recommendations/impact/config")
    assert response.status_code == 200
    body = response.json()
    assert body["impact"] == "recommendation"
    assert body["attribution"]


# ------------------------------------------------------------------ ui ---


def test_ui_wires_impact_comparison():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    assert "loadImpactComparison" in html
    assert "positioning-impact" in html
    assert "/api/v1/recommendations/impact" in html
    assert "Uygulanırsa" in html
    assert "Uygulanmazsa" in html
