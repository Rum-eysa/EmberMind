"""EM-081 chronological operator event timeline tests (Epic E8).

The timeline merges the live change feed (fire_event / forecast / alert) and
operator-accepted recommendations (EM-047 accept/edit) into one newest-first
stream for shift handover. These tests pin the merge, the ordering, the
category / event filters, the "unknown filter not swallowed" contract, the
limit clamping and the read-only HTTP endpoints.
"""
from datetime import timedelta

from src.models.live import LiveUpdate
from src.models.recommendation import RecommendationDecision
from src.services.event_timeline import (
    TIMELINE_ATTRIBUTION,
    TIMELINE_CATEGORIES,
    TIMELINE_PERSISTENCE,
    event_timeline,
    timeline_config,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Page-size stub so default and max limits are exercised explicitly."""

    def __init__(self, default=50, maximum=200):
        self.EVENT_TIMELINE_DEFAULT_LIMIT = default
        self.EVENT_TIMELINE_MAX_LIMIT = maximum


def _live(session, kind, at, *, event_key="evt-1", title=None, message=None):
    session.add(
        LiveUpdate(
            kind=kind,
            event_key=event_key,
            title=title or f"{kind} başlık",
            message=message or f"{kind} mesaj",
            source="test",
            created_at=at,
            updated_at=at,
        )
    )


def _decision(
    session,
    key,
    at,
    *,
    action="accept",
    event_key="evt-1",
    resource="UNIT-1",
    reason=None,
    decided_by="op",
):
    session.add(
        RecommendationDecision(
            decision_key=key,
            event_key=event_key,
            resource_key=resource,
            action=action,
            reason=reason,
            decided_by=decided_by,
            detail_json="{}",
            created_at=at,
            updated_at=at,
        )
    )


def _seed_all_four(session):
    """One of every category, with strictly increasing timestamps."""
    base = utc_now()
    _live(session, "fire_event", base - timedelta(minutes=40), event_key="E-A")
    _live(session, "forecast", base - timedelta(minutes=30), event_key="E-A")
    _decision(session, "dec-1", base - timedelta(minutes=20), event_key="E-B")
    _live(session, "alert", base - timedelta(minutes=10), event_key="E-A")
    session.flush()


# --------------------------------------------------------------------------- #
# Merge + categories
# --------------------------------------------------------------------------- #
def test_merges_all_four_categories(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings())
    cats = {e["category"] for e in result["entries"]}
    assert cats == set(TIMELINE_CATEGORIES)
    assert result["total_matching"] == 4


def test_every_entry_carries_label_and_ref(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings())
    for entry in result["entries"]:
        assert entry["category_label"]
        assert entry["ref"]["table"] in ("live_updates", "recommendation_decisions")
        assert entry["at"] is not None


def test_edit_counts_as_accepted(session):
    base = utc_now()
    _decision(session, "dec-edit", base, action="edit")
    session.flush()
    result = event_timeline(session, _Settings())
    assert result["entries"][0]["category"] == "accepted_recommendation"
    assert "düzenlenerek" in result["entries"][0]["title"]


def test_reject_is_not_included(session):
    base = utc_now()
    _decision(session, "dec-rej", base, action="reject")
    session.flush()
    result = event_timeline(session, _Settings())
    assert result["total_matching"] == 0
    assert result["entries"] == []


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #
def test_sorted_newest_first(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings())
    ats = [e["at"] for e in result["entries"]]
    assert ats == sorted(ats, reverse=True)
    # The most recent entry is the alert (base - 10 min).
    assert result["entries"][0]["category"] == "alert"


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def test_event_key_filter(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings(), event_key="E-A")
    assert {e["event_key"] for e in result["entries"]} == {"E-A"}
    assert result["filter"]["event_key"] == "E-A"


def test_category_filter_valid(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings(), category="forecast")
    assert result["filter"]["category"] == "forecast"
    assert all(e["category"] == "forecast" for e in result["entries"])


def test_category_filter_case_insensitive(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings(), category=" FORECAST ")
    assert result["filter"]["category"] == "forecast"


def test_unknown_category_not_swallowed(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings(), category="bogus")
    assert result["filter"]["category"] is None
    assert result["filter"]["requested_category"] == "bogus"
    # Unknown filter returns the unfiltered stream rather than an empty one.
    assert result["total_matching"] == 4


def test_category_counts_reflect_stream(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings())
    counts = result["category_counts"]
    assert counts["fire_event"] == 1
    assert counts["forecast"] == 1
    assert counts["alert"] == 1
    assert counts["accepted_recommendation"] == 1


# --------------------------------------------------------------------------- #
# Limits + clamping + metadata
# --------------------------------------------------------------------------- #
def test_limit_bounds_page_size(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings(), limit=2)
    assert len(result["entries"]) == 2
    assert result["limit"] == 2
    # The whole matching stream is still reported even when the page is smaller.
    assert result["total_matching"] == 4


def test_limit_clamped_to_max(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings(maximum=3), limit=999)
    assert result["limit"] == 3


def test_defaults_without_settings():
    config = timeline_config()
    assert config["default_limit"] == 50
    assert config["max_limit"] == 200


def test_read_only_projection_metadata(session):
    _seed_all_four(session)
    result = event_timeline(session, _Settings())
    assert result["persistence"] == TIMELINE_PERSISTENCE == "none"
    assert result["attribution"] == TIMELINE_ATTRIBUTION
    assert result["generated_at"]


def test_config_lists_categories_and_sources():
    config = timeline_config(_Settings())
    codes = [c["code"] for c in config["categories"]]
    assert codes == list(TIMELINE_CATEGORIES)
    assert len(config["sources"]) == 2


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_returns_stream(client, session):
    _seed_all_four(session)
    session.commit()
    resp = client.get("/api/v1/event-timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "event_timeline"
    assert body["total_matching"] == 4


def test_endpoint_category_filter(client, session):
    _seed_all_four(session)
    session.commit()
    resp = client.get("/api/v1/event-timeline", params={"category": "alert"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["filter"]["category"] == "alert"
    assert all(e["category"] == "alert" for e in body["entries"])


def test_endpoint_config(client):
    resp = client.get("/api/v1/event-timeline/config")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["categories"]) == 4
