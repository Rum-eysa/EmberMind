"""EM-051 field task instruction card tests.

A field team needs a short card from an accepted proposal: target (incident +
coordinates), arrival (ETA) and a risk note. The card is reconstructed from the
EM-047 decision audit so it survives the unit leaving the "available" pool.
These tests pin the card content, the audit-sourced reconstruction, the risk
note from the EM-029 engine, the HTTP surface and the operator-map wiring.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.recommendation_decision import record_decision
from src.services.task_instruction import (
    TaskInstructionError,
    generate_task_cards,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Settings stub with the EM-029 bands and the 30/60/120 dk horizons."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


def _resource(session, key="RES-1", status="available"):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=f"{key} crew",
            resource_type="crew",
            latitude=38.0,
            longitude=27.0,
            status=status,
            capacity=10.0,
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


_DETAIL = {
    "name": "Alpha crew",
    "resource_type": "crew",
    "eta_minutes": 25,
    "distance_km": 12.5,
}


# ------------------------------------------------------------ service ---


def test_accept_produces_card_with_target_eta_and_risk_note(session):
    _resource(session, "RES-1")
    _resource(session, "RES-IDLE")  # stays available -> measurable capacity
    _event(session, "EVT-A")
    # One available crew (2.0 ha/h) against 6 ha at T+30 (12 ha/h demand).
    _forecast(session, "EVT-A", 30, 6.0)
    record_decision(
        session,
        resource_key="RES-1",
        action="accept",
        event_key="EVT-A",
        decided_by="op-1",
        detail=_DETAIL,
    )
    cards = generate_task_cards(session, _Settings(), "EVT-A")
    assert len(cards) == 1
    card = cards[0]
    assert card["resource_key"] == "RES-1"
    assert card["resource_name"] == "RES-1 crew"  # live record wins over snapshot
    assert card["resource_status"] == "en_route"
    assert card["target"]["name"] == "EVT-A fire"
    assert card["target"]["latitude"] == pytest.approx(38.0)
    assert card["target"]["longitude"] == pytest.approx(27.0)
    assert card["eta_minutes"] == 25
    assert card["distance_km"] == 12.5
    assert card["risk_note"] is not None
    assert card["risk_note"]["level"] == "kritik"
    assert card["risk_note"]["horizon_minutes"] == 30
    assert card["accepted_at"]
    assert card["decided_by"] == "op-1"


def test_reject_produces_no_card(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    record_decision(
        session,
        resource_key="RES-1",
        action="reject",
        event_key="EVT-A",
        reason="not needed",
    )
    assert generate_task_cards(session, _Settings(), "EVT-A") == []


def test_edit_produces_card_with_arrival_minutes(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    record_decision(
        session,
        resource_key="RES-1",
        action="edit",
        event_key="EVT-A",
        arrival_minutes=40,
        detail={"name": "Bravo", "resource_type": "crew"},
    )
    cards = generate_task_cards(session, _Settings(), "EVT-A")
    assert len(cards) == 1
    # No eta_minutes in the snapshot -> falls back to the edited arrival.
    assert cards[0]["eta_minutes"] == 40


def test_unknown_event_raises(session):
    with pytest.raises(TaskInstructionError):
        generate_task_cards(session, _Settings(), "EVT-GHOST")


def test_cards_filter_by_event_and_list_all_without_filter(session):
    _resource(session, "RES-1")
    _resource(session, "RES-2")
    _event(session, "EVT-A")
    _event(session, "EVT-B")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    record_decision(session, resource_key="RES-2", action="accept", event_key="EVT-B")
    only_a = generate_task_cards(session, _Settings(), "EVT-A")
    assert [c["event_key"] for c in only_a] == ["EVT-A"]
    both = generate_task_cards(session, _Settings())
    assert [c["event_key"] for c in both] == ["EVT-A", "EVT-B"]


def test_newest_decision_per_resource_event(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    record_decision(
        session,
        resource_key="RES-1",
        action="accept",
        event_key="EVT-A",
        detail=dict(_DETAIL, eta_minutes=30),
    )
    record_decision(
        session,
        resource_key="RES-1",
        action="accept",
        event_key="EVT-A",
        detail=dict(_DETAIL, eta_minutes=15),
    )
    cards = generate_task_cards(session, _Settings(), "EVT-A")
    assert len(cards) == 1
    assert cards[0]["eta_minutes"] == 15


def test_card_survives_after_unit_leaves_available_pool(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    record_decision(
        session,
        resource_key="RES-1",
        action="accept",
        event_key="EVT-A",
        detail=_DETAIL,
    )
    # Accepted units are "en_route" and drop out of live EM-052 proposals; the
    # audit-sourced card must still be produced.
    resource = session.query(SuppressionResource).filter_by(resource_key="RES-1").one()
    assert resource.status == "en_route"
    cards = generate_task_cards(session, _Settings(), "EVT-A")
    assert len(cards) == 1
    assert cards[0]["resource_status"] == "en_route"


def test_travel_mode_and_arrival_eta_are_carried(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    arrival = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=25)
    record_decision(
        session,
        resource_key="RES-1",
        action="accept",
        event_key="EVT-A",
        arrival_minutes=25,
        detail=dict(_DETAIL, travel_mode="air"),
    )
    resource = session.query(SuppressionResource).filter_by(resource_key="RES-1").one()
    resource.arrival_eta = arrival
    session.flush()
    cards = generate_task_cards(session, _Settings(), "EVT-A")
    assert cards[0]["travel_mode"] == "air"
    assert cards[0]["arrival_eta"]


def test_missing_resource_falls_back_to_snapshot(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    record_decision(
        session,
        resource_key="RES-1",
        action="accept",
        event_key="EVT-A",
        detail=_DETAIL,
    )
    session.execute(
        delete(SuppressionResource).where(SuppressionResource.resource_key == "RES-1")
    )
    session.flush()
    cards = generate_task_cards(session, _Settings(), "EVT-A")
    assert len(cards) == 1
    assert cards[0]["resource_name"] == "Alpha crew"  # from the audit snapshot
    assert cards[0]["resource_type"] == "crew"
    assert cards[0]["resource_status"] is None


def test_deleted_target_event_yields_no_card(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    session.execute(delete(FireEvent).where(FireEvent.event_key == "EVT-A"))
    session.flush()
    # No explicit filter: the card is skipped because its target is gone.
    assert generate_task_cards(session, _Settings()) == []


def test_risk_note_absent_when_no_forecasts(session):
    _resource(session, "RES-1")
    _event(session, "EVT-A")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    cards = generate_task_cards(session, _Settings(), "EVT-A")
    assert len(cards) == 1
    assert cards[0]["risk_note"] is None


# ----------------------------------------------------------- endpoint ---


def test_endpoint_task_cards_after_accept(client, session):
    _event(session, "EVT-HTTP")
    _resource(session, "RES-HTTP")
    session.commit()
    accepted = client.post(
        "/api/v1/recommendations/decisions",
        json={
            "resource_key": "RES-HTTP",
            "action": "accept",
            "event_key": "EVT-HTTP",
            "detail": _DETAIL,
        },
    )
    assert accepted.status_code == 200
    body = client.get("/api/v1/recommendations/task-cards?event_key=EVT-HTTP").json()
    assert body["count"] == 1
    assert body["event_key"] == "EVT-HTTP"
    card = body["cards"][0]
    assert card["target"]["name"] == "EVT-HTTP fire"
    assert card["eta_minutes"] == 25
    assert body["attribution"]


def test_endpoint_task_cards_unknown_event_404(client):
    res = client.get("/api/v1/recommendations/task-cards?event_key=EVT-GHOST")
    assert res.status_code == 404
    assert res.json()["detail"]["status"] == "not_found"


def test_endpoint_task_cards_config(client):
    body = client.get("/api/v1/recommendations/task-cards/config").json()
    assert body["source"]
    assert set(body["fields"]) == {"target", "eta_minutes", "risk_note"}
    assert body["persistence"] == "none"
    assert body["attribution"]


# ------------------------------------------------------------------ ui ---


def test_ui_wires_task_cards():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    assert "toggleTaskCards" in html
    assert "loadTaskCards" in html
    assert "renderTaskCard" in html
    assert "refreshTaskCards" in html
    assert "/api/v1/recommendations/task-cards" in html
    assert "Görev kartları" in html
