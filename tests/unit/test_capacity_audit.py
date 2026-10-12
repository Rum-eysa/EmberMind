"""EM-034 capacity-assumption audit-trail unit tests.

The edit surface itself (per-type ha/hour assumptions, validation) came with
EM-028. EM-034 adds the durable history: every applied change is recorded with
the editor and timestamp, re-saving the same value is not audited, and the
history is readable newest-first with a resource-type filter and a clamped page
size.
"""
import pytest

from src.services.capacity import (
    CAPACITY_AUDIT_ATTRIBUTION,
    CapacityError,
    list_assumptions,
    list_audit,
    update_assumptions,
)


class _Settings:
    # The audit page bounds fall back to the service defaults when these are
    # present as plain ints (real config always provides them).
    CAPACITY_AUDIT_DEFAULT_LIMIT = 50
    CAPACITY_AUDIT_MAX_LIMIT = 5


def _crew_audit(entries):
    return [e for e in entries if e["resource_type"] == "crew"]


# --------------------------------------------------------------------------
# Service: recording a change
# --------------------------------------------------------------------------
def test_first_edit_writes_one_audit_row(session):
    result = update_assumptions(session, _Settings(), {"crew": 3.0}, "zeynep")
    assert result["applied_count"] == 1
    audit = list_audit(session, _Settings())
    assert audit["total_matching"] == 1
    row = audit["entries"][0]
    assert row["resource_type"] == "crew"
    assert row["old_value"] == pytest.approx(2.0)
    assert row["new_value"] == pytest.approx(3.0)
    assert row["updated_by"] == "zeynep"
    assert row["changed_at"] and row["changed_at"].endswith("Z")


def test_same_value_reread_is_not_a_change(session):
    # Reading assumptions seeds the rows from defaults but writes no audit.
    list_assumptions(session, _Settings())
    assert list_audit(session, _Settings())["total_matching"] == 0


def test_re_saving_same_value_adds_no_audit(session):
    update_assumptions(session, _Settings(), {"crew": 5.0}, "deniz")
    before = list_audit(session, _Settings())["total_matching"]
    result = update_assumptions(session, _Settings(), {"crew": 5.0}, "deniz")
    assert result["applied_count"] == 0
    after = list_audit(session, _Settings())["total_matching"]
    assert after == before


def test_multiple_types_each_audited_once(session):
    result = update_assumptions(session, _Settings(), {"crew": 2.5, "uav": 6.0}, "irem")
    assert result["applied_count"] == 2
    audit = list_audit(session, _Settings())
    types = {e["resource_type"] for e in audit["entries"]}
    assert types == {"crew", "uav"}


def test_partial_change_only_audits_changed_type(session):
    update_assumptions(session, _Settings(), {"crew": 4.0}, "a")
    # crew already 4.0 (unchanged), uav moves -> only the uav edit is audited.
    result = update_assumptions(session, _Settings(), {"crew": 4.0, "uav": 7.0}, "b")
    assert result["applied_count"] == 1
    crews = _crew_audit(list_audit(session, _Settings())["entries"])
    # the single earlier crew change is still the only crew row.
    assert len(crews) == 1


def test_audit_newest_first(session):
    update_assumptions(session, _Settings(), {"crew": 3.0}, "first")
    update_assumptions(session, _Settings(), {"crew": 9.0}, "second")
    crews = _crew_audit(list_audit(session, _Settings())["entries"])
    assert crews[0]["updated_by"] == "second"
    assert crews[0]["new_value"] == pytest.approx(9.0)
    assert crews[1]["new_value"] == pytest.approx(3.0)


def test_list_audit_filters_by_resource_type(session):
    update_assumptions(session, _Settings(), {"crew": 3.0, "uav": 8.0}, "op")
    audit = list_audit(session, _Settings(), resource_type="uav")
    assert audit["total_matching"] == 1
    assert audit["entries"][0]["resource_type"] == "uav"


def test_list_audit_clamps_limit_to_max(session):
    for value in (3.0, 4.0, 5.0, 6.0, 7.0, 8.0):
        update_assumptions(session, _Settings(), {"crew": value}, "op")
    audit = list_audit(session, _Settings(), limit=999)
    assert audit["limit"] == 5  # CAPACITY_AUDIT_MAX_LIMIT
    assert len(audit["entries"]) == 5
    assert audit["total_matching"] == 6


def test_list_audit_exposes_unit_and_attribution(session):
    update_assumptions(session, _Settings(), {"crew": 3.0}, "op")
    audit = list_audit(session, _Settings())
    assert audit["unit"] == "ha/saat"
    assert audit["attribution"] == CAPACITY_AUDIT_ATTRIBUTION


# --------------------------------------------------------------------------
# Service: validation is preserved (criterion #3)
# --------------------------------------------------------------------------
def test_negative_value_raises_and_writes_no_audit(session):
    with pytest.raises(CapacityError):
        update_assumptions(session, _Settings(), {"crew": -1.0}, "op")
    assert list_audit(session, _Settings())["total_matching"] == 0


def test_non_numeric_value_raises(session):
    with pytest.raises(CapacityError):
        update_assumptions(session, _Settings(), {"crew": "fast"}, "op")


def test_empty_update_raises(session):
    with pytest.raises(CapacityError):
        update_assumptions(session, _Settings(), {}, "op")


# --------------------------------------------------------------------------
# HTTP endpoints
# --------------------------------------------------------------------------
def test_put_returns_audit_and_persists_change(client):
    res = client.put(
        "/api/v1/capacity/assumptions",
        json={"helicopter": 15.0, "updated_by": "mert"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "updated"
    assert body["applied_count"] == 1
    heli = next(a for a in body["assumptions"] if a["resource_type"] == "helicopter")
    assert heli["ha_per_hour"] == pytest.approx(15.0)
    assert any(
        e["resource_type"] == "helicopter" and e["updated_by"] == "mert"
        for e in body["audit"]
    )


def test_audit_endpoint_reflects_put(client):
    client.put(
        "/api/v1/capacity/assumptions",
        json={"crew": 6.0, "updated_by": "elif"},
    )
    res = client.get("/api/v1/capacity/assumptions/audit")
    assert res.status_code == 200
    data = res.json()
    assert data["total_matching"] >= 1
    crew = _crew_audit(data["entries"])
    assert crew and crew[0]["updated_by"] == "elif"


def test_audit_endpoint_filters_by_type(client):
    client.put(
        "/api/v1/capacity/assumptions",
        json={"crew": 6.0, "uav": 9.0, "updated_by": "can"},
    )
    res = client.get(
        "/api/v1/capacity/assumptions/audit", params={"resource_type": "uav"}
    )
    assert res.status_code == 200
    entries = res.json()["entries"]
    assert all(e["resource_type"] == "uav" for e in entries)
    assert len(entries) == 1


def test_audit_endpoint_empty_history(client):
    res = client.get("/api/v1/capacity/assumptions/audit")
    assert res.status_code == 200
    assert res.json()["entries"] == []


def test_put_invalid_value_returns_400(client):
    res = client.put(
        "/api/v1/capacity/assumptions",
        json={"crew": -3.0, "updated_by": "x"},
    )
    assert res.status_code == 400
