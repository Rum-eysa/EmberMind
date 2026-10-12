"""EM-082 multi-fire management survey tests (Epic E8).

The survey merges three existing sources at read time - active ``FireEvent``
rows, ``SuppressionResource`` statuses and the EM-047/EM-053 decision audit (the
same "newest accept/edit while still busy" rule that backs the double-booking
guard) - into a per-fire roster plus three deterministic cross-fire conflict
buckets. These tests pin the active-only ordering, the roster derivation, the
orphan / contended-base / understaffed-critical warnings, the global-vs-scoped
conflict contract, the ``max_events`` bound and the read-only HTTP endpoints.
"""
from datetime import timedelta

from src.models.inventory import SuppressionResource
from src.models.recommendation import RecommendationDecision
from src.models.spatial import FireEvent
from src.services.multi_fire import (
    MULTI_FIRE_ATTRIBUTION,
    MULTI_FIRE_PERSISTENCE,
    multi_fire_config,
    multi_fire_overview,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Bound the survey page so the ``max_events`` path is exercised."""

    def __init__(self, max_events=50):
        self.MULTI_FIRE_MAX_EVENTS = max_events


def _fire(session, key, *, severity="medium", status="active", minutes_ago=0):
    now = utc_now()
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} yangını",
            latitude=37.75,
            longitude=28.0,
            min_lat=37.7,
            max_lat=37.8,
            min_lon=27.9,
            max_lon=28.1,
            geometry_wkt="POINT(37.75 28.0)",
            severity=severity,
            status=status,
            started_at=now - timedelta(minutes=minutes_ago),
        )
    )


def _unit(
    session,
    key,
    *,
    status="available",
    base_key=None,
    resource_type="crew",
):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=f"{key} birimi",
            resource_type=resource_type,
            latitude=37.75,
            longitude=28.0,
            base_key=base_key,
            status=status,
        )
    )


def _decision(session, *, resource, event, action="accept"):
    session.add(
        RecommendationDecision(
            decision_key=f"dec-{resource}-{action}-{event}",
            resource_key=resource,
            event_key=event,
            action=action,
            detail_json="{}",
        )
    )


def _roster_keys(data, event_key):
    for ev in data["events"]:
        if ev["event_key"] == event_key:
            return {u["resource_key"] for u in ev["committed"]}
    return set()


# --------------------------------------------------------------------------- #
# Active survey + ordering
# --------------------------------------------------------------------------- #
def test_lists_active_events_only(session):
    _fire(session, "E-A", status="active")
    _fire(session, "E-B", status="active")
    _fire(session, "E-X", status="contained")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    keys = {ev["event_key"] for ev in data["events"]}
    assert keys == {"E-A", "E-B"}
    assert data["active_event_total"] == 2


def test_events_ordered_by_severity(session):
    _fire(session, "E-low", severity="low", minutes_ago=0)
    _fire(session, "E-crit", severity="critical", minutes_ago=5)
    _fire(session, "E-med", severity="medium", minutes_ago=1)
    session.flush()
    data = multi_fire_overview(session, _Settings())
    order = [ev["severity"] for ev in data["events"]]
    assert order[0] == "critical"
    assert order == ["critical", "medium", "low"]


def test_max_events_bounds_survey(session):
    _fire(session, "E-crit", severity="critical")
    _fire(session, "E-low", severity="low")
    session.flush()
    data = multi_fire_overview(session, _Settings(max_events=1))
    assert data["active_event_total"] == 1
    assert data["events"][0]["severity"] == "critical"


# --------------------------------------------------------------------------- #
# Roster derivation (reuses the EM-053 active-assignment rule)
# --------------------------------------------------------------------------- #
def test_committed_unit_in_roster(session):
    _fire(session, "E-A")
    _unit(session, "U1", status="en_route", base_key="B1")
    _decision(session, resource="U1", event="E-A", action="accept")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert _roster_keys(data, "E-A") == {"U1"}


def test_release_supersedes_accept(session):
    _fire(session, "E-A")
    _unit(session, "U1", status="en_route", base_key="B1")
    # accept (older) then a later release - the newest row wins, so not committed.
    _decision(session, resource="U1", event="E-A", action="accept")
    _decision(session, resource="U1", event="E-A", action="release")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert _roster_keys(data, "E-A") == set()
    # Busy but provenance-blind after release: not asserted as an orphan either.
    assert data["conflicts"]["orphaned_units"] == []


def test_edit_counts_as_committed(session):
    _fire(session, "E-A")
    _unit(session, "U1", status="deployed")
    _decision(session, resource="U1", event="E-A", action="edit")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert _roster_keys(data, "E-A") == {"U1"}


# --------------------------------------------------------------------------- #
# Conflict buckets
# --------------------------------------------------------------------------- #
def test_orphaned_unit_on_inactive_fire(session):
    _fire(session, "E-A", status="contained")
    _unit(session, "U1", status="en_route")
    _decision(session, resource="U1", event="E-A", action="accept")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    orphans = data["conflicts"]["orphaned_units"]
    assert [o["resource_key"] for o in orphans] == ["U1"]
    assert data["has_conflicts"] is True


def test_contended_base_across_two_fires(session):
    _fire(session, "E-A")
    _fire(session, "E-B")
    _unit(session, "U1", status="en_route", base_key="B1")
    _unit(session, "U2", status="deployed", base_key="B1")
    _decision(session, resource="U1", event="E-A", action="accept")
    _decision(session, resource="U2", event="E-B", action="accept")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    bases = data["conflicts"]["contended_bases"]
    assert len(bases) == 1
    assert bases[0]["base_key"] == "B1"
    assert set(bases[0]["events"]) == {"E-A", "E-B"}


def test_single_fire_base_is_not_contended(session):
    _fire(session, "E-A")
    _unit(session, "U1", status="en_route", base_key="B1")
    _unit(session, "U2", status="deployed", base_key="B1")
    _decision(session, resource="U1", event="E-A", action="accept")
    _decision(session, resource="U2", event="E-A", action="accept")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert data["conflicts"]["contended_bases"] == []


def test_understaffed_critical_flagged(session):
    _fire(session, "E-crit", severity="critical")
    _unit(session, "U1", status="available")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    under = data["conflicts"]["understaffed_critical"]
    assert [u["event_key"] for u in under] == ["E-crit"]


def test_understaffed_low_severity_not_flagged(session):
    _fire(session, "E-low", severity="low")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert data["conflicts"]["understaffed_critical"] == []


def test_no_conflicts_when_balanced(session):
    _fire(session, "E-A", severity="high")
    _unit(session, "U1", status="en_route", base_key="B1")
    _decision(session, resource="U1", event="E-A", action="accept")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert data["has_conflicts"] is False
    assert data["conflict_count"] == 0


# --------------------------------------------------------------------------- #
# Totals + scoping + metadata
# --------------------------------------------------------------------------- #
def test_totals_count_pools(session):
    _fire(session, "E-A")
    _unit(session, "U1", status="en_route", base_key="B1")
    _unit(session, "U2", status="available")
    _unit(session, "U3", status="available")
    _decision(session, resource="U1", event="E-A", action="accept")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert data["totals"]["busy_units"] == 1
    assert data["totals"]["available_units"] == 2
    assert data["totals"]["committed_units"] == 1


def test_event_key_scopes_events_but_conflicts_stay_global(session):
    _fire(session, "E-A")
    _fire(session, "E-B")
    _unit(session, "U1", status="en_route", base_key="B1")
    _unit(session, "U2", status="deployed", base_key="B1")
    _decision(session, resource="U1", event="E-A", action="accept")
    _decision(session, resource="U2", event="E-B", action="accept")
    session.flush()
    data = multi_fire_overview(session, _Settings(), event_key="E-A")
    assert data["event_count"] == 1
    assert data["active_event_total"] == 2
    # The contended base spans both fires and is still reported under one scope.
    assert len(data["conflicts"]["contended_bases"]) == 1


def test_read_only_projection_metadata(session):
    _fire(session, "E-A")
    session.flush()
    data = multi_fire_overview(session, _Settings())
    assert data["persistence"] == MULTI_FIRE_PERSISTENCE == "none"
    assert data["attribution"] == MULTI_FIRE_ATTRIBUTION
    assert data["generated_at"]


def test_config_payload():
    config = multi_fire_config(_Settings())
    assert [s["code"] for s in config["severities"]] == [
        "critical",
        "high",
        "medium",
        "low",
    ]
    assert len(config["conflict_types"]) == 3
    assert len(config["sources"]) == 3


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_returns_survey(client, session):
    _fire(session, "E-A")
    _unit(session, "U1", status="en_route", base_key="B1")
    _decision(session, resource="U1", event="E-A", action="accept")
    session.commit()
    resp = client.get("/api/v1/multi-fire")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "multi_fire"
    assert body["active_event_total"] == 1


def test_endpoint_config(client):
    resp = client.get("/api/v1/multi-fire/config")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["conflict_types"]) == 3
