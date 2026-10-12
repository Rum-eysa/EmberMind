"""EM-084 mobile/tablet field view tests.

The field view composes two existing engines into one phone-legible projection:
the team's EM-051 task card(s) and the nearest EM-029 active risk zones, ranked
by great-circle distance from the team's reference point (its own coordinates, or
else the first card's target). These tests pin the reference resolution, the
distance ranking / radius filter / item cap, the risk severity carried on a
nearby zone, the resource filter, the HTTP surface and the operator-map wiring.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.field_view import (
    FieldViewError,
    field_view,
    field_view_config,
)
from src.services.recommendation_decision import record_decision
from src.utils.timeutils import utc_now


class _Settings:
    """Lightweight settings stub: EM-029 bands + EM-084 proximity knobs."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    FIELD_VIEW_RADIUS_KM = 25.0
    FIELD_VIEW_MAX_ITEMS = 5


_DETAIL = {
    "name": "Alpha crew",
    "resource_type": "crew",
    "eta_minutes": 25,
    "distance_km": 12.5,
}


def _resource(session, key="RES-1", status="available", capacity=10.0):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=f"{key} crew",
            resource_type="crew",
            latitude=38.0,
            longitude=27.0,
            status=status,
            capacity=capacity,
        )
    )
    session.flush()


def _event(session, key, status="active", lat=38.0, lon=27.0):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} fire",
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.05,
            max_lat=lat + 0.05,
            min_lon=lon - 0.05,
            max_lon=lon + 0.05,
            geometry_wkt=f"POINT({lon} {lat})",
            status=status,
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            source="manual",
        )
    )
    session.flush()


def _forecast(session, event, horizon, area_ha):
    session.add(
        FireForecast(
            event_key=event,
            model_name="rothermel_v1",
            latitude=38.0,
            longitude=27.0,
            predicted_area_ha=area_ha,
            geometry_wkt="POLYGON((27 38,27.01 38,27.01 38.01,27 38.01,27 38))",
            forecast_for=utc_now(),
            horizon_minutes=horizon,
            rate_of_spread_m_per_min=10.0,
            spread_direction_deg=45.0,
            inputs_json="{}",
        )
    )
    session.flush()


def _accept(session, resource_key, event_key):
    record_decision(
        session,
        resource_key=resource_key,
        action="accept",
        event_key=event_key,
        decided_by="op-1",
        detail=_DETAIL,
    )


# ------------------------------------------------------------ service ---


def test_explicit_location_returns_empty_view_without_error(session):
    # No committed cards, but an explicit position is a legitimate field view.
    result = field_view(session, _Settings(), latitude=38.0, longitude=27.0)
    assert result["panel"] == "field_view"
    assert result["card_count"] == 0
    assert result["nearby_count"] == 0
    assert result["reference"]["origin"] == "coordinates"
    assert result["persistence"] == "none"


def test_no_cards_and_no_location_returns_empty(session):
    # Nothing anchored: an empty (not error) view so the UI shows its empty state.
    result = field_view(session, _Settings())
    assert result["card_count"] == 0
    assert result["reference"]["origin"] == "none"
    assert result["nearby_risks"] == []


def test_unknown_event_raises_field_view_error(session):
    with pytest.raises(FieldViewError):
        field_view(session, _Settings(), event_key="EVT-GHOST")


def test_reference_defaults_to_first_card_target(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A", lat=38.0, lon=27.0)
    _accept(session, "RES-1", "EVT-A")
    result = field_view(session, _Settings(), event_key="EVT-A")
    assert result["card_count"] == 1
    assert result["reference"]["origin"] == "task_card_target"
    assert result["reference"]["latitude"] == pytest.approx(38.0)
    assert result["reference"]["longitude"] == pytest.approx(27.0)


def test_nearby_ranked_by_distance_and_radius_filtered(session):
    # Reference at (38.0, 27.0). Three active incidents along the same parallel.
    _event(session, "EVT-NEAR", lat=38.0, lon=27.0)  # 0 km
    _event(session, "EVT-MID", lat=38.0, lon=27.1)  # ~8.5 km
    _event(session, "EVT-FAR", lat=38.0, lon=28.2)  # ~103 km -> out of 25 km
    result = field_view(session, _Settings(), latitude=38.0, longitude=27.0)
    keys = [row["event_key"] for row in result["nearby_risks"]]
    assert keys == ["EVT-NEAR", "EVT-MID"]  # nearest first, far excluded
    assert result["nearby_risks"][0]["distance_km"] == pytest.approx(0.0, abs=0.1)
    assert result["nearby_risks"][0]["bearing_deg"] is None  # coincident point


def test_contained_event_not_surfaced_as_nearby(session):
    _event(session, "EVT-ACT", lat=38.0, lon=27.0)
    _event(session, "EVT-OUT", lat=38.0, lon=27.02, status="contained")
    result = field_view(session, _Settings(), latitude=38.0, longitude=27.0)
    keys = [row["event_key"] for row in result["nearby_risks"]]
    assert "EVT-OUT" not in keys
    assert "EVT-ACT" in keys


def test_max_items_caps_nearby_count(session):
    _event(session, "EVT-1", lat=38.0, lon=27.0)
    _event(session, "EVT-2", lat=38.0, lon=27.01)
    _event(session, "EVT-3", lat=38.0, lon=27.02)
    settings = _Settings()
    settings.FIELD_VIEW_MAX_ITEMS = 2
    result = field_view(session, settings, latitude=38.0, longitude=27.0)
    assert result["nearby_count"] == 2
    assert len(result["nearby_risks"]) == 2


def test_nearby_carries_risk_severity(session):
    # One available crew (2.0 ha/h) vs a critical forecast at T+30 for EVT-A.
    _resource(session, "RES-1")
    _resource(session, "RES-IDLE")
    _event(session, "EVT-A", lat=38.0, lon=27.0)
    _forecast(session, "EVT-A", 30, 6.0)
    _accept(session, "RES-1", "EVT-A")
    # Reference far from EVT-A so the accepted card's own target is not the one
    # measured; but keep within radius by using the same location instead.
    result = field_view(session, _Settings(), latitude=38.0, longitude=27.0)
    nearby = {row["event_key"]: row for row in result["nearby_risks"]}
    assert nearby["EVT-A"]["peak_level"] == "kritik"
    assert nearby["EVT-A"]["peak_risk_index"] is not None


def test_explicit_location_overrides_card_reference(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A", lat=38.0, lon=27.0)
    _accept(session, "RES-1", "EVT-A")
    result = field_view(
        session, _Settings(), latitude=39.0, longitude=27.0, event_key="EVT-A"
    )
    assert result["reference"]["origin"] == "coordinates"
    assert result["reference"]["latitude"] == pytest.approx(39.0)


def test_resource_key_filters_cards(session):
    _resource(session, "RES-1")
    _resource(session, "RES-2")
    _event(session, "EVT-A", lat=38.0, lon=27.0)
    _event(session, "EVT-B", lat=38.0, lon=27.0)
    _accept(session, "RES-1", "EVT-A")
    _accept(session, "RES-2", "EVT-B")
    result = field_view(
        session, _Settings(), resource_key="RES-1", latitude=38.0, longitude=27.0
    )
    assert result["card_count"] == 1
    assert result["cards"][0]["resource_key"] == "RES-1"


def test_attribution_and_persistence_present(session):
    result = field_view(session, _Settings(), latitude=38.0, longitude=27.0)
    assert result["attribution"]
    assert result["card_attribution"]
    assert result["persistence"] == "none"


# ------------------------------------------------------------ config ---


def test_config_shape():
    cfg = field_view_config(_Settings())
    assert cfg["panel"] == "field_view"
    assert cfg["radius_km"] == pytest.approx(25.0)
    assert cfg["max_items"] == 5
    assert cfg["persistence"] == "none"
    assert "kritik" in cfg["risk_levels"]
    assert "task_cards" in cfg["sources"]


def test_config_radius_clamped_high():
    settings = _Settings()
    settings.FIELD_VIEW_RADIUS_KM = 10_000.0
    cfg = field_view_config(settings)
    assert cfg["radius_km"] == pytest.approx(500.0)


# ----------------------------------------------------------- endpoint ---


def test_endpoint_config(client):
    body = client.get("/api/v1/field-view/config").json()
    assert body["panel"] == "field_view"
    assert body["persistence"] == "none"
    assert body["sources"]["risk_zones"].startswith("EM-029")


def test_endpoint_view_with_coordinates(client, session):
    _event(session, "EVT-HTTP", lat=38.0, lon=27.0)
    session.commit()
    res = client.get("/api/v1/field-view?latitude=38.0&longitude=27.0")
    assert res.status_code == 200
    body = res.json()
    assert body["reference"]["origin"] == "coordinates"
    keys = [row["event_key"] for row in body["nearby_risks"]]
    assert "EVT-HTTP" in keys


def test_endpoint_view_empty_ok(client):
    res = client.get("/api/v1/field-view")
    assert res.status_code == 200
    body = res.json()
    assert body["card_count"] == 0


def test_endpoint_view_unknown_event_404(client):
    res = client.get("/api/v1/field-view?event_key=EVT-GHOST")
    assert res.status_code == 404
    assert res.json()["detail"]["status"] == "not_found"


def test_endpoint_out_of_radius_excluded(client, session):
    _event(session, "EVT-FAR", lat=45.0, lon=27.0)
    session.commit()
    res = client.get("/api/v1/field-view?latitude=38.0&longitude=27.0")
    body = res.json()
    keys = [row["event_key"] for row in body["nearby_risks"]]
    assert "EVT-FAR" not in keys


# ------------------------------------------------------------------ ui ---


def test_ui_wires_field_view():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    assert "toggleFieldViewPanel" in html
    assert "loadFieldView" in html
    assert "renderFieldView" in html
    assert "/api/v1/field-view" in html
    assert "fieldview-open" in html
    # EM-084 is explicitly about mobile/tablet legibility.
    assert "@media" in html
    assert "Saha Görünümü" in html
