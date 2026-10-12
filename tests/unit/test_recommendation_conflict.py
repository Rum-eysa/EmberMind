"""EM-053 double-assignment / resource-conflict prevention tests.

The coordinator must never book the same unit to two incidents at once, must get
a descriptive warning on a conflicting attempt, and a unit must return to
``available`` automatically when its incident is no longer active. These tests
pin the conflict guard, the explicit + automatic release, the active-assignment
listing, the HTTP surface (409 conflict / release / assignments) and the
operator-map integration. No new table is used - the booking is read from the
EM-047 audit trail itself.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent
from src.services.recommendation_decision import (
    ConflictError,
    DecisionError,
    list_active_assignments,
    record_decision,
    release_assignment,
    release_completed_assignments,
)


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


def _event(session, key, status="active"):
    lat, lon = 38.0, 27.0
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


# ------------------------------------------------------------- service ---


def test_cross_event_assignment_conflicts(session):
    _resource(session, "RES-1")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    with pytest.raises(ConflictError):
        record_decision(
            session, resource_key="RES-1", action="accept", event_key="EVT-B"
        )


def test_same_event_reaccept_is_idempotent(session):
    _resource(session, "RES-1")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    again = record_decision(
        session, resource_key="RES-1", action="accept", event_key="EVT-A"
    )
    assert again["resource_status_after"] == "en_route"


def test_edit_conflicts_when_booked_elsewhere(session):
    _resource(session, "RES-1")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    with pytest.raises(ConflictError):
        record_decision(
            session,
            resource_key="RES-1",
            action="edit",
            event_key="EVT-B",
            arrival_minutes=20,
        )


def test_release_frees_for_reassignment(session):
    _resource(session, "RES-1")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    rel = release_assignment(session, resource_key="RES-1")
    assert rel["released"] is True
    assert rel["resource_status_after"] == "available"
    # Now the same unit can serve a different incident.
    second = record_decision(
        session, resource_key="RES-1", action="accept", event_key="EVT-B"
    )
    assert second["resource_status_after"] == "en_route"


def test_release_idle_is_noop(session):
    _resource(session, "RES-1", status="available")
    rel = release_assignment(session, resource_key="RES-1")
    assert rel["released"] is False
    assert rel["reason"] == "not_assigned"


def test_release_wrong_event_conflicts(session):
    _resource(session, "RES-1")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    with pytest.raises(ConflictError):
        release_assignment(session, resource_key="RES-1", event_key="EVT-B")


def test_release_unknown_resource_raises(session):
    with pytest.raises(DecisionError):
        release_assignment(session, resource_key="ghost")


def test_active_assignment_listing(session):
    _event(session, "EVT-A", status="active")
    _resource(session, "RES-1")
    record_decision(session, resource_key="RES-1", action="accept", event_key="EVT-A")
    rows = list_active_assignments(session)
    assert len(rows) == 1
    assert rows[0]["resource_key"] == "RES-1"
    assert rows[0]["event_key"] == "EVT-A"
    assert rows[0]["event_status"] == "active"


def test_auto_release_completed_incident(session):
    _event(session, "EVT-LIVE", status="active")
    _event(session, "EVT-DONE", status="contained")
    _resource(session, "RES-LIVE")
    _resource(session, "RES-DONE")
    record_decision(
        session, resource_key="RES-LIVE", action="accept", event_key="EVT-LIVE"
    )
    record_decision(
        session, resource_key="RES-DONE", action="accept", event_key="EVT-DONE"
    )

    result = release_completed_assignments(session)
    released_keys = {r["resource_key"] for r in result["released"]}
    assert released_keys == {"RES-DONE"}
    assert result["count"] == 1

    live = session.scalar(
        select(SuppressionResource).where(
            SuppressionResource.resource_key == "RES-LIVE"
        )
    )
    done = session.scalar(
        select(SuppressionResource).where(
            SuppressionResource.resource_key == "RES-DONE"
        )
    )
    assert live.status == "en_route"
    assert done.status == "available"


def test_auto_release_missing_incident(session):
    # A booking whose incident row is gone counts as completed -> auto released.
    _resource(session, "RES-1")
    record_decision(
        session, resource_key="RES-1", action="accept", event_key="EVT-GONE"
    )
    result = release_completed_assignments(session)
    assert result["count"] == 1
    assert result["released"][0]["resource_key"] == "RES-1"


# ------------------------------------------------------------ endpoint ---


def test_endpoint_conflict_returns_409(client, session):
    _resource(session, "RES-HTTP")
    session.commit()
    first = client.post(
        "/api/v1/recommendations/decisions",
        json={"resource_key": "RES-HTTP", "action": "accept", "event_key": "EVT-A"},
    )
    assert first.status_code == 200
    conflict = client.post(
        "/api/v1/recommendations/decisions",
        json={"resource_key": "RES-HTTP", "action": "accept", "event_key": "EVT-B"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["status"] == "conflict"


def test_endpoint_release_and_assignments(client, session):
    _event(session, "EVT-A", status="active")
    _resource(session, "RES-HTTP")
    session.commit()
    client.post(
        "/api/v1/recommendations/decisions",
        json={"resource_key": "RES-HTTP", "action": "accept", "event_key": "EVT-A"},
    )
    listed = client.get("/api/v1/recommendations/assignments").json()
    assert listed["count"] == 1
    rel = client.post(
        "/api/v1/recommendations/decisions/release",
        json={"resource_key": "RES-HTTP", "event_key": "EVT-A"},
    )
    assert rel.status_code == 200
    assert rel.json()["released"] is True
    after = client.get("/api/v1/recommendations/assignments").json()
    assert after["count"] == 0


def test_endpoint_release_unknown_404(client):
    rel = client.post(
        "/api/v1/recommendations/decisions/release",
        json={"resource_key": "ghost"},
    )
    assert rel.status_code == 404


def test_endpoint_release_completed(client, session):
    _event(session, "EVT-DONE", status="contained")
    _resource(session, "RES-DONE")
    session.commit()
    client.post(
        "/api/v1/recommendations/decisions",
        json={"resource_key": "RES-DONE", "action": "accept", "event_key": "EVT-DONE"},
    )
    swept = client.post("/api/v1/recommendations/assignments/release-completed")
    assert swept.status_code == 200
    assert swept.json()["count"] == 1


def test_endpoint_config_exposes_conflict(client):
    body = client.get("/api/v1/recommendations/decisions/config").json()
    # EM-047 contract stays intact...
    assert set(body["actions"]) == {"accept", "reject", "edit"}
    # ...and EM-053 conflict prevention is described alongside it.
    cp = body["conflict_prevention"]
    assert cp["single_active_assignment"] is True
    assert cp["conflict_http_status"] == 409
    assert cp["auto_release_on_completion"] is True


# ------------------------------------------------------------------ ui ---


def test_ui_wires_assignment_release():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    assert "toggleAssignments" in html
    assert "loadAssignments" in html
    assert "/api/v1/recommendations/assignments" in html
    assert "/api/v1/recommendations/decisions/release" in html
    assert "Müsaite al" in html
