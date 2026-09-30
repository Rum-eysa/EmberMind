"""EM-047 operator recommendation-decision tests.

Covers the accept / reject / edit service workflow (status commit to "yolda",
optional reject reason, audit row for every decision, list/get), the HTTP
endpoints, and the operator_map.html integration that renders a decision toolbar
on each positioning proposal.
"""
import pytest
from sqlalchemy import select

from src.models.inventory import SuppressionResource
from src.services.recommendation_decision import (
    DecisionError,
    get_decision,
    list_decisions,
    record_decision,
)


def _resource(session, key="RES-1", status="available"):
    row = SuppressionResource(
        resource_key=key,
        name=f"{key} crew",
        resource_type="crew",
        latitude=38.0,
        longitude=27.0,
        status=status,
        capacity=10.0,
    )
    session.add(row)
    session.flush()
    return row


# --- service ---------------------------------------------------------------
def test_accept_commits_resource_and_audits(session):
    _resource(session, "RES-1", status="available")
    res = record_decision(
        session,
        resource_key="RES-1",
        action="accept",
        event_key="EVT-1",
        proposal_id="prop-0-RES-1",
        decided_by="operator",
    )
    assert res["resource_status_before"] == "available"
    assert res["resource_status_after"] == "en_route"
    assert res["status_changed"] is True
    assert res["decision"]["action"] == "accept"
    assert res["decision"]["detail"]["proposal_id"] == "prop-0-RES-1"
    assert len(list_decisions(session, event_key="EVT-1")) == 1


def test_edit_commits_with_arrival_override(session):
    _resource(session, "RES-2", status="available")
    res = record_decision(
        session,
        resource_key="RES-2",
        action="edit",
        arrival_minutes=30,
        reason="yakıt ikmali sonrası",
    )
    assert res["resource_status_after"] == "en_route"
    assert res["decision"]["action"] == "edit"
    assert res["decision"]["detail"]["arrival_minutes"] == 30
    assert res["decision"]["reason"] == "yakıt ikmali sonrası"
    row = session.scalar(
        select(SuppressionResource).where(SuppressionResource.resource_key == "RES-2")
    )
    assert row is not None and row.arrival_eta is not None


def test_reject_keeps_status_and_reason_is_optional(session):
    _resource(session, "RES-3", status="available")
    with_reason = record_decision(
        session, resource_key="RES-3", action="reject", reason="daha yakın birlik var"
    )
    assert with_reason["resource_status_after"] == "available"
    assert with_reason["status_changed"] is False
    assert with_reason["decision"]["reason"] == "daha yakın birlik var"

    no_reason = record_decision(session, resource_key="RES-3", action="reject")
    assert no_reason["decision"]["reason"] is None
    # Both rejects are audited even though nothing changed on the resource.
    assert len(list_decisions(session, resource_key="RES-3", action="reject")) == 2


def test_invalid_action_raises(session):
    _resource(session, "RES-4")
    with pytest.raises(DecisionError):
        record_decision(session, resource_key="RES-4", action="defer")


def test_unknown_resource_raises(session):
    with pytest.raises(DecisionError):
        record_decision(session, resource_key="ghost", action="accept")


def test_get_decision_and_missing(session):
    _resource(session, "RES-5")
    entry = record_decision(session, resource_key="RES-5", action="accept")["decision"]
    assert get_decision(session, entry["decision_key"])["id"] == entry["id"]
    with pytest.raises(DecisionError):
        get_decision(session, "dec-does-not-exist")


# --- HTTP endpoints --------------------------------------------------------
def test_endpoint_config(client):
    body = client.get("/api/v1/recommendations/decisions/config").json()
    assert set(body["actions"]) == {"accept", "reject", "edit"}
    assert body["commit_status"] == "en_route"
    assert body["reject_reason_required"] is False


def test_endpoint_accept_records_and_lists(client, session):
    _resource(session, "RES-HTTP")
    session.commit()
    rec = client.post(
        "/api/v1/recommendations/decisions",
        json={
            "resource_key": "RES-HTTP",
            "action": "accept",
            "event_key": "EVT-9",
            "proposal_id": "prop-0-RES-HTTP",
        },
    )
    assert rec.status_code == 200
    payload = rec.json()
    assert payload["resource_status_after"] == "en_route"
    key = payload["decision"]["decision_key"]
    assert client.get(f"/api/v1/recommendations/decisions/{key}").status_code == 200
    listed = client.get(
        "/api/v1/recommendations/decisions?event_key=EVT-9&action=accept"
    ).json()
    assert listed["count"] == 1


def test_endpoint_missing_resource_is_404(client):
    res = client.post(
        "/api/v1/recommendations/decisions",
        json={"resource_key": "ghost", "action": "accept"},
    )
    assert res.status_code == 404


def test_endpoint_invalid_action_is_400(client, session):
    _resource(session, "RES-BAD")
    session.commit()
    res = client.post(
        "/api/v1/recommendations/decisions",
        json={"resource_key": "RES-BAD", "action": "maybe"},
    )
    assert res.status_code == 400


def test_endpoint_get_missing_is_404(client):
    assert client.get("/api/v1/recommendations/decisions/dec-nope").status_code == 404


# --- UI integration --------------------------------------------------------
def test_operator_map_has_decision_toolbar():
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[2] / "src" / "static" / "operator_map.html"
    ).read_text(encoding="utf-8")
    assert "db-accept" in html
    assert "db-reject" in html
    assert "decideProposal(" in html
    assert "/api/v1/recommendations/decisions" in html
