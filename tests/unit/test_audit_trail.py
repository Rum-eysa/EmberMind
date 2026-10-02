"""EM-096 unified immutable audit trail tests (Epic E10).

The ledger gives a manager one cross-subsystem accountability trail: who made
which decision / change, when, and how (old -> new). These tests pin:

* controlled-vocabulary validation (unknown domain / action rejected),
* mandatory actor + non-empty summary,
* the value-snapshot round-trip (old_value -> new_value, dict or scalar),
* append-only behaviour (recording twice keeps both rows, newest first),
* the immutability guarantee - the service exposes no update / delete / purge,
* read never writes (an untouched ledger lists empty, count_by_domain empty),
* limit clamping to ``AUDIT_MAX_LIMIT``,
* filtering by domain / actor / subject_key, and
* the HTTP endpoints (config, overview feed, POST record incl. a 400 on an
  invalid vocabulary).
"""
import inspect

import pytest
from sqlalchemy import select

from src.models.audit_trail import AuditTrailEntry
from src.services import audit_trail
from src.services.audit_trail import (
    AUDIT_ACTIONS,
    AUDIT_DOMAINS,
    AuditError,
    audit_config,
    count_by_domain,
    list_audit,
    record_audit,
)


class _Settings:
    """Audit bounds mirroring the config defaults for service tests."""

    AUDIT_DEFAULT_LIMIT = 50
    AUDIT_MAX_LIMIT = 500


def _record(
    session, *, domain="recommendation", action="accept", actor="operators@a", **detail
):
    return record_audit(session, _Settings(), domain, action, actor, detail or None)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def test_record_writes_immutable_row(session):
    entry = _record(
        session,
        subject_key="EVT-7",
        summary="Operatör öneriyi kabul etti",
        old_value={"status": "available"},
        new_value={"status": "en_route"},
    )
    assert entry["domain"] == "recommendation"
    assert entry["action"] == "accept"
    assert entry["actor"] == "operators@a"
    assert entry["subject_key"] == "EVT-7"
    assert entry["audit_key"].startswith("aud-")
    assert entry["old_value"] == {"status": "available"}
    assert entry["new_value"] == {"status": "en_route"}
    assert entry["created_at"]  # "ne zaman"
    assert session.scalar(select(AuditTrailEntry)) is not None


def test_unknown_domain_rejected(session):
    with pytest.raises(AuditError):
        record_audit(session, _Settings(), "not_a_domain", "create", "a")


def test_unknown_action_rejected(session):
    with pytest.raises(AuditError):
        record_audit(session, _Settings(), "recommendation", "teleport", "a")


def test_missing_actor_rejected(session):
    with pytest.raises(AuditError):
        record_audit(session, _Settings(), "threshold", "update", "   ")


def test_summary_defaults_to_domain_action(session):
    entry = _record(session, domain="threshold", action="update", actor="ops")
    assert entry["summary"] == "threshold.update"


def test_scalar_value_snapshot_round_trip(session):
    entry = _record(
        session,
        domain="capacity_assumption",
        action="update",
        actor="admin",
        old_value=2.0,
        new_value=3.0,
    )
    assert entry["old_value"] == 2.0
    assert entry["new_value"] == 3.0


def test_create_has_no_old_value(session):
    entry = _record(
        session,
        domain="webhook",
        action="create",
        actor="ops",
        new_value={"url": "https://x"},
    )
    assert entry["old_value"] is None
    assert entry["new_value"] == {"url": "https://x"}


# --------------------------------------------------------------------------
# append-only + immutability
# --------------------------------------------------------------------------
def test_recording_is_append_only(session):
    first = _record(session, actor="a1", summary="bir")
    second = _record(session, actor="a2", summary="iki")
    listing = list_audit(session, _Settings())
    keys = [e["audit_key"] for e in listing["entries"]]
    # newest first, both present, distinct rows
    assert keys == [second["audit_key"], first["audit_key"]]
    assert listing["total_matching"] == 2


def test_service_exposes_no_mutation_surface():
    # "kayıtlar silinemez": there is deliberately no update/delete/purge path.
    names = set(dir(audit_trail))
    for banned in ("update_audit", "delete_audit", "purge", "clear", "edit_audit"):
        assert banned not in names
    funcs = [name for name, obj in inspect.getmembers(audit_trail, inspect.isfunction)]
    assert any(f.startswith("record") for f in funcs)
    assert not any(f.startswith(("delete", "update", "purge", "clear")) for f in funcs)


def test_read_never_writes(session):
    listing = list_audit(session, _Settings())
    assert listing["entries"] == []
    assert listing["total_matching"] == 0
    assert count_by_domain(session) == {}
    # still empty after reading
    assert list_audit(session, _Settings())["entries"] == []


# --------------------------------------------------------------------------
# limit clamping + filtering
# --------------------------------------------------------------------------
def test_limit_clamped_to_max(session):
    for i in range(3):
        _record(session, actor=f"ops{i}")
    listing = list_audit(session, _Settings(), limit=99999)
    assert listing["limit"] == 500


def test_default_limit_when_none(session):
    listing = list_audit(session, _Settings())
    assert listing["limit"] == 50


def test_filter_by_domain(session):
    _record(session, domain="recommendation", actor="a")
    _record(session, domain="threshold", actor="a")
    listing = list_audit(session, _Settings(), domain="threshold")
    assert [e["domain"] for e in listing["entries"]] == ["threshold"]


def test_filter_by_actor(session):
    _record(session, actor="alice")
    _record(session, actor="bob")
    listing = list_audit(session, _Settings(), actor="alice")
    assert all(e["actor"] == "alice" for e in listing["entries"])
    assert listing["total_matching"] == 1


def test_filter_by_subject_key(session):
    _record(session, actor="a", subject_key="EVT-1")
    _record(session, actor="a", subject_key="EVT-2")
    listing = list_audit(session, _Settings(), subject_key="EVT-2")
    assert len(listing["entries"]) == 1
    assert listing["entries"][0]["subject_key"] == "EVT-2"


def test_count_by_domain(session):
    _record(session, domain="recommendation", actor="a")
    _record(session, domain="recommendation", actor="a")
    _record(session, domain="scenario", actor="a")
    counts = count_by_domain(session)
    assert counts == {"recommendation": 2, "scenario": 1}


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
def test_config_exposes_vocabularies_and_policy():
    cfg = audit_config(_Settings())
    assert cfg["domains"] == list(AUDIT_DOMAINS)
    assert cfg["actions"] == list(AUDIT_ACTIONS)
    assert cfg["immutable"] is True
    assert cfg["persistence"] == "append_only"


# --------------------------------------------------------------------------
# HTTP endpoints
# --------------------------------------------------------------------------
def test_endpoint_config(client):
    res = client.get("/api/v1/audit/config")
    assert res.status_code == 200
    body = res.json()
    assert "recommendation" in body["domains"]
    assert body["immutable"] is True


def test_endpoint_record_and_overview(client, session):
    res = client.post(
        "/api/v1/audit",
        json={
            "domain": "capacity_assumption",
            "action": "update",
            "actor": "admin@agency",
            "subject_key": "crew",
            "summary": "ha/saat 2.0 -> 3.0",
            "old_value": 2.0,
            "new_value": 3.0,
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "recorded"

    over = client.get("/api/v1/audit")
    assert over.status_code == 200
    body = over.json()
    assert body["total_matching"] >= 1
    assert body["counts_by_domain"].get("capacity_assumption", 0) >= 1
    newest = body["entries"][0]
    assert newest["actor"] == "admin@agency"
    assert newest["old_value"] == 2.0
    assert newest["new_value"] == 3.0


def test_endpoint_record_invalid_returns_400(client):
    res = client.post(
        "/api/v1/audit",
        json={"domain": "nope", "action": "create", "actor": "a"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["status"] == "error"


def test_endpoint_overview_filter(client, session):
    client.post(
        "/api/v1/audit",
        json={"domain": "threshold", "action": "update", "actor": "ops"},
    )
    res = client.get("/api/v1/audit", params={"domain": "threshold"})
    assert res.status_code == 200
    assert all(e["domain"] == "threshold" for e in res.json()["entries"])
