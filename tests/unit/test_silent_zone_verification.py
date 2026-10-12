"""EM-041 operator verification workflow tests (Epic E4).

EM-041 lets an operator mark an EM-040 silent-region alert as *verified* /
*false alarm* / *under review*. Unlike the read-only E4 panels it **writes**:
each marking appends an immutable audit row (the previous verdict is never
overwritten), the *current* verdict is the newest row, and a feedback summary
turns the recorded verdicts into a model-improvement signal (false-alarm rate
over decisive verdicts only). These tests pin the append-only rule, the current
verdict collapse, the feedback math, the status/limit validation and the HTTP
endpoints.
"""
import pytest

from src.models.spatial import SilentRegion
from src.models.silent_zone_verification import (
    VERIFICATION_LABELS,
    VERIFICATION_STATUSES,
)
from src.services.silent_zone_verification import (
    SILENT_ZONE_VERIFICATION_ATTRIBUTION,
    SILENT_ZONE_VERIFICATION_PERSISTENCE,
    SilentZoneVerificationError,
    current_verdicts,
    feedback_summary,
    get_current_verification,
    list_verifications,
    record_verification,
    verification_config,
)

_REGION = (37.0, 38.0, 27.0, 28.0)


class _Settings:
    """Stub exposing only the EM-041 limit knob so ``_max_limit`` reads it."""

    def __init__(self, max_limit=200):
        self.SILENT_VERIFICATION_MAX_LIMIT = max_limit


def _add_region(session, name):
    region = SilentRegion(
        region_name=name,
        reason="test bölge",
        min_lat=_REGION[0],
        max_lat=_REGION[1],
        min_lon=_REGION[2],
        max_lon=_REGION[3],
        geometry_wkt="",
        is_active=True,
    )
    session.add(region)
    session.flush()
    return region


# --------------------------------------------------------------------------- #
# record_verification
# --------------------------------------------------------------------------- #
def test_record_appends_and_snapshots_name(session):
    region = _add_region(session, "Alpha")
    result = record_verification(
        session, region_id=region.id, status="verified", verified_by="op-1"
    )
    verdict = result["verification"]
    assert verdict["region_id"] == region.id
    # region_name defaults to the region's own name when not supplied.
    assert verdict["region_name"] == "Alpha"
    assert verdict["status"] == "verified"
    assert verdict["status_label"] == VERIFICATION_LABELS["verified"]
    assert result["is_new_current"] is True
    assert result["prior_verifications"] == 0


def test_record_rejects_unknown_status(session):
    region = _add_region(session, "Alpha")
    with pytest.raises(SilentZoneVerificationError, match="invalid status"):
        record_verification(session, region_id=region.id, status="resolved")


def test_record_rejects_missing_region(session):
    with pytest.raises(SilentZoneVerificationError, match="not found"):
        record_verification(session, region_id=999999, status="verified")


def test_record_is_append_only(session):
    region = _add_region(session, "Alpha")
    record_verification(session, region_id=region.id, status="under_review")
    second = record_verification(session, region_id=region.id, status="false_alarm")
    # The prior verdict is preserved, not overwritten.
    assert second["prior_verifications"] == 1
    rows = list_verifications(session, region_id=region.id)
    assert len(rows) == 2


def test_record_status_is_normalised(session):
    region = _add_region(session, "Alpha")
    result = record_verification(session, region_id=region.id, status="  Verified  ")
    assert result["verification"]["status"] == "verified"


# --------------------------------------------------------------------------- #
# current verdict resolution
# --------------------------------------------------------------------------- #
def test_get_current_returns_newest(session):
    region = _add_region(session, "Alpha")
    record_verification(session, region_id=region.id, status="verified")
    record_verification(session, region_id=region.id, status="false_alarm")
    current = get_current_verification(session, region.id)
    assert current["status"] == "false_alarm"


def test_get_current_none_when_unmarked(session):
    region = _add_region(session, "Alpha")
    assert get_current_verification(session, region.id) is None


def test_current_verdicts_collapses_history(session):
    alpha = _add_region(session, "Alpha")
    beta = _add_region(session, "Beta")
    record_verification(session, region_id=alpha.id, status="under_review")
    record_verification(session, region_id=alpha.id, status="verified")
    record_verification(session, region_id=beta.id, status="false_alarm")
    verdicts = current_verdicts(session)
    assert set(verdicts) == {alpha.id, beta.id}
    assert verdicts[alpha.id]["status"] == "verified"
    assert verdicts[alpha.id]["status_label"] == VERIFICATION_LABELS["verified"]
    assert verdicts[beta.id]["status"] == "false_alarm"


# --------------------------------------------------------------------------- #
# list_verifications
# --------------------------------------------------------------------------- #
def test_list_newest_first_and_filters(session):
    region = _add_region(session, "Alpha")
    record_verification(session, region_id=region.id, status="verified")
    record_verification(session, region_id=region.id, status="false_alarm")
    rows = list_verifications(session)
    assert rows[0]["status"] == "false_alarm"  # newest first
    filtered = list_verifications(session, status="verified")
    assert len(filtered) == 1
    assert filtered[0]["status"] == "verified"


def test_list_rejects_unknown_status_filter(session):
    with pytest.raises(SilentZoneVerificationError, match="invalid status"):
        list_verifications(session, status="bogus")


def test_list_clips_limit_to_max(session):
    region = _add_region(session, "Alpha")
    for status in VERIFICATION_STATUSES:
        record_verification(session, region_id=region.id, status=status)
    # A requested limit above the configured max is clipped, not honoured.
    rows = list_verifications(session, limit=9999)
    assert len(rows) == len(VERIFICATION_STATUSES)


# --------------------------------------------------------------------------- #
# feedback_summary
# --------------------------------------------------------------------------- #
def test_feedback_empty_has_no_rate(session):
    summary = feedback_summary(session)
    assert summary["total_verifications"] == 0
    assert summary["false_alarm_rate"] is None
    assert summary["adjudicated_region_count"] == 0


def test_feedback_counts_and_rate(session):
    alpha = _add_region(session, "Alpha")
    beta = _add_region(session, "Beta")
    gamma = _add_region(session, "Gamma")
    record_verification(session, region_id=alpha.id, status="verified")
    record_verification(session, region_id=beta.id, status="verified")
    record_verification(session, region_id=gamma.id, status="false_alarm")
    summary = feedback_summary(session)
    assert summary["total_verifications"] == 3
    assert summary["by_status"]["verified"] == 2
    assert summary["by_status"]["false_alarm"] == 1
    assert summary["decisive_verifications"] == 3
    assert summary["false_alarm_rate"] == round(1 / 3, 4)
    assert summary["adjudicated_region_count"] == 3


def test_feedback_under_review_not_decisive(session):
    region = _add_region(session, "Alpha")
    record_verification(session, region_id=region.id, status="under_review")
    summary = feedback_summary(session)
    assert summary["under_review_verifications"] == 1
    assert summary["decisive_verifications"] == 0
    assert summary["false_alarm_rate"] is None
    # A parked region is not counted as adjudicated.
    assert summary["adjudicated_region_count"] == 0


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_config_payload():
    config = verification_config(_Settings(max_limit=50))
    assert config["persistence"] == SILENT_ZONE_VERIFICATION_PERSISTENCE
    assert config["attribution"] == SILENT_ZONE_VERIFICATION_ATTRIBUTION
    assert config["max_limit"] == 50
    assert [s["code"] for s in config["statuses"]] == list(VERIFICATION_STATUSES)
    assert "yanlış alarm oranı" in config["feedback_signal"]


def test_config_defaults_without_settings():
    config = verification_config()
    assert config["max_limit"] == 200


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_config(client):
    resp = client.get("/api/v1/silent-zone-verifications/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persistence"] == SILENT_ZONE_VERIFICATION_PERSISTENCE


def test_endpoint_record_and_read_back(client, session):
    region = _add_region(session, "Alpha")
    session.commit()
    resp = client.post(
        "/api/v1/silent-zone-verifications",
        json={"region_id": region.id, "status": "verified", "verified_by": "op-2"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "recorded"
    listing = client.get("/api/v1/silent-zone-verifications").json()
    assert listing["count"] == 1
    assert listing["verifications"][0]["status"] == "verified"


def test_endpoint_record_rejects_bad_status(client, session):
    region = _add_region(session, "Alpha")
    session.commit()
    resp = client.post(
        "/api/v1/silent-zone-verifications",
        json={"region_id": region.id, "status": "maybe"},
    )
    assert resp.status_code == 400


def test_endpoint_record_missing_region_is_404(client):
    resp = client.post(
        "/api/v1/silent-zone-verifications",
        json={"region_id": 424242, "status": "verified"},
    )
    assert resp.status_code == 404


def test_endpoint_current_all_and_single(client, session):
    region = _add_region(session, "Alpha")
    session.commit()
    client.post(
        "/api/v1/silent-zone-verifications",
        json={"region_id": region.id, "status": "false_alarm"},
    )
    every = client.get("/api/v1/silent-zone-verifications/current").json()
    assert every["count"] == 1
    assert every["verdicts"][0]["status"] == "false_alarm"
    one = client.get(
        "/api/v1/silent-zone-verifications/current", params={"region_id": region.id}
    ).json()
    assert one["verification"]["status"] == "false_alarm"


def test_endpoint_feedback(client, session):
    region = _add_region(session, "Alpha")
    session.commit()
    client.post(
        "/api/v1/silent-zone-verifications",
        json={"region_id": region.id, "status": "verified"},
    )
    client.post(
        "/api/v1/silent-zone-verifications",
        json={"region_id": region.id, "status": "false_alarm"},
    )
    body = client.get("/api/v1/silent-zone-verifications/feedback").json()
    assert body["total_verifications"] == 2
    assert body["false_alarm_rate"] == 0.5
    assert body["persistence"] == SILENT_ZONE_VERIFICATION_PERSISTENCE


def test_endpoint_list_rejects_bad_limit(client):
    resp = client.get("/api/v1/silent-zone-verifications", params={"limit": 0})
    assert resp.status_code == 422
