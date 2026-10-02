"""EM-089 shift-handover notes + one-click summary tests (Epic E8).

Pins the free-text note surface (add / list / get / delete), its validation
(empty note, unknown incident, blank key) and the read-time handover summary
that merges the operator's notes with EM-081's chronological stream and
EM-082's committed rosters. The acceptance contract - "notes are visible on the
timeline" - is checked directly: a stored note appears in the summary's
``chronology`` under the ``operator_note`` category without EM-081 gaining a
new category. The HTTP endpoints (including the 400 / 404 mapping) round it out.
"""
import pytest

from src.models.live import LiveUpdate
from src.models.spatial import FireEvent
from src.services.shift_handover import (
    HANDOVER_ATTRIBUTION,
    HANDOVER_PERSISTENCE,
    NOTE_CATEGORY,
    ShiftHandoverError,
    add_note,
    delete_note,
    get_note,
    handover_config,
    handover_summary,
    list_notes,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Page caps for the three surfaces the summary composes."""

    SHIFT_HANDOVER_MAX_NOTES = 5
    EVENT_TIMELINE_DEFAULT_LIMIT = 50
    EVENT_TIMELINE_MAX_LIMIT = 200
    MULTI_FIRE_MAX_EVENTS = 50


def _event(session, key, *, status="active", severity="high"):
    """Seed a minimal fire event and return it."""
    row = FireEvent(
        event_key=key,
        name=f"{key} olay",
        latitude=38.0,
        longitude=27.5,
        min_lat=37.95,
        max_lat=38.05,
        min_lon=27.45,
        max_lon=27.55,
        geometry_wkt="POINT(27.5 38)",
        severity=severity,
        status=status,
        started_at=utc_now().replace(tzinfo=None),
    )
    session.add(row)
    session.flush()
    return row


def _live(session, kind, *, event_key="evt-1", title="t", message="m"):
    session.add(
        LiveUpdate(
            kind=kind,
            event_key=event_key,
            title=title,
            message=message,
            source="test",
        )
    )
    session.flush()


# --------------------------------------------------------------------------- #
# add_note
# --------------------------------------------------------------------------- #
def test_add_note_returns_persisted_shape(session):
    _event(session, "evt-1")
    note = add_note(session, _Settings(), event_key="evt-1", body="Su noktası boş.")
    assert note["event_key"] == "evt-1"
    assert note["body"] == "Su noktası boş."
    assert note["id"] > 0
    assert note["created_at"]


def test_add_note_trims_body_and_author(session):
    _event(session, "evt-1")
    note = add_note(
        session, _Settings(), event_key="evt-1", body="  yol dar  ", author="  ay  "
    )
    assert note["body"] == "yol dar"
    assert note["author"] == "ay"


def test_add_note_blank_author_stored_as_none(session):
    _event(session, "evt-1")
    note = add_note(session, _Settings(), event_key="evt-1", body="x", author="   ")
    assert note["author"] is None


def test_add_note_empty_body_raises(session):
    _event(session, "evt-1")
    with pytest.raises(ShiftHandoverError):
        add_note(session, _Settings(), event_key="evt-1", body="   ")


def test_add_note_unknown_event_raises_not_found(session):
    with pytest.raises(ShiftHandoverError, match="not found"):
        add_note(session, _Settings(), event_key="ghost", body="x")


def test_add_note_blank_event_key_raises(session):
    with pytest.raises(ShiftHandoverError):
        add_note(session, _Settings(), event_key="  ", body="x")


# --------------------------------------------------------------------------- #
# list_notes
# --------------------------------------------------------------------------- #
def test_list_notes_empty(session):
    data = list_notes(session, _Settings())
    assert data["panel"] == "event_notes"
    assert data["count"] == 0
    assert data["total_matching"] == 0
    assert data["notes"] == []


def test_list_notes_newest_first(session):
    _event(session, "evt-1")
    first = add_note(session, _Settings(), event_key="evt-1", body="bir")
    second = add_note(session, _Settings(), event_key="evt-1", body="iki")
    data = list_notes(session, _Settings())
    assert [n["id"] for n in data["notes"]] == [second["id"], first["id"]]


def test_list_notes_filter_by_event(session):
    _event(session, "evt-1")
    _event(session, "evt-2")
    add_note(session, _Settings(), event_key="evt-1", body="a")
    add_note(session, _Settings(), event_key="evt-2", body="b")
    data = list_notes(session, _Settings(), event_key="evt-2")
    assert data["total_matching"] == 1
    assert data["notes"][0]["event_key"] == "evt-2"


def test_list_notes_limit_clamped_to_max(session):
    _event(session, "evt-1")
    for i in range(7):
        add_note(session, _Settings(), event_key="evt-1", body=f"n{i}")
    data = list_notes(session, _Settings())
    # SHIFT_HANDOVER_MAX_NOTES = 5 caps even the unbounded request.
    assert data["count"] == 5
    assert data["total_matching"] == 7
    assert data["max_notes"] == 5


# --------------------------------------------------------------------------- #
# get / delete
# --------------------------------------------------------------------------- #
def test_get_note_roundtrip(session):
    _event(session, "evt-1")
    note = add_note(session, _Settings(), event_key="evt-1", body="canlı")
    assert get_note(session, note["id"])["body"] == "canlı"


def test_get_note_missing_raises(session):
    with pytest.raises(ShiftHandoverError, match="bulunamadı"):
        get_note(session, 999)


def test_delete_note_removes_it(session):
    _event(session, "evt-1")
    note = add_note(session, _Settings(), event_key="evt-1", body="silinecek")
    result = delete_note(session, note["id"])
    assert result["deleted"] == note["id"]
    assert list_notes(session, _Settings())["count"] == 0


def test_delete_note_missing_raises(session):
    with pytest.raises(ShiftHandoverError, match="bulunamadı"):
        delete_note(session, 123)


# --------------------------------------------------------------------------- #
# handover_summary
# --------------------------------------------------------------------------- #
def test_summary_lists_active_incidents_only(session):
    _event(session, "evt-1", status="active")
    _event(session, "evt-2", status="contained")
    data = handover_summary(session, _Settings())
    keys = {row["event_key"] for row in data["incidents"]}
    assert keys == {"evt-1"}
    assert data["incident_count"] == 1


def test_summary_note_visible_in_chronology(session):
    """Acceptance #2: the operator note joins the timeline stream."""
    _event(session, "evt-1")
    _live(session, "fire_event", event_key="evt-1", title="Yangın başladı")
    add_note(session, _Settings(), event_key="evt-1", body="Rüzgar kuzeyden")
    data = handover_summary(session, _Settings())
    categories = {entry["category"] for entry in data["chronology"]}
    assert NOTE_CATEGORY in categories
    assert "fire_event" in categories
    note_entry = next(e for e in data["chronology"] if e["category"] == NOTE_CATEGORY)
    assert note_entry["text"] == "Rüzgar kuzeyden"
    assert data["notes_in_view"] == 1


def test_summary_scoped_to_one_event(session):
    _event(session, "evt-1")
    _event(session, "evt-2")
    add_note(session, _Settings(), event_key="evt-1", body="bir")
    add_note(session, _Settings(), event_key="evt-2", body="iki")
    data = handover_summary(session, _Settings(), event_key="evt-2")
    assert data["incident_count"] == 1
    assert data["incidents"][0]["event_key"] == "evt-2"
    assert all(e["event_key"] == "evt-2" for e in data["chronology"])


def test_summary_carries_note_count_and_card_fields(session):
    _event(session, "evt-1", severity="critical")
    add_note(session, _Settings(), event_key="evt-1", body="erişim anlaşması")
    add_note(session, _Settings(), event_key="evt-1", body="su noktası")
    data = handover_summary(session, _Settings())
    card = data["incidents"][0]
    assert card["note_count"] == 2
    assert card["latest_note"] == "su noktası"
    assert card["severity"] == "critical"
    assert data["note_count"] == 2


def test_summary_conflict_block_present(session):
    _event(session, "evt-1")
    data = handover_summary(session, _Settings())
    for key in ("orphaned_units", "contended_bases", "understaffed_critical", "total"):
        assert key in data["conflicts"]


def test_summary_metadata(session):
    data = handover_summary(session, _Settings())
    assert data["panel"] == "shift_handover"
    assert data["attribution"] == HANDOVER_ATTRIBUTION
    assert data["persistence"] == HANDOVER_PERSISTENCE == "event_notes"


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_config_payload(session):
    cfg = handover_config(_Settings())
    assert cfg["note_category"] == NOTE_CATEGORY
    assert cfg["max_notes"] == 5
    assert any("event_notes" in src for src in cfg["sources"])


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_config(client):
    resp = client.get("/api/v1/shift-handover/config")
    assert resp.status_code == 200
    assert resp.json()["note_category"] == NOTE_CATEGORY


def test_endpoint_add_and_list(client, session):
    _event(session, "evt-1")
    session.commit()
    resp = client.post(
        "/api/v1/shift-handover/notes",
        json={"event_key": "evt-1", "body": "kaya düşmesi", "author": "op"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "created"
    listing = client.get("/api/v1/shift-handover/notes")
    assert listing.status_code == 200
    bodies = [n["body"] for n in listing.json()["notes"]]
    assert "kaya düşmesi" in bodies


def test_endpoint_add_unknown_event_404(client):
    resp = client.post(
        "/api/v1/shift-handover/notes",
        json={"event_key": "ghost", "body": "x"},
    )
    assert resp.status_code == 404


def test_endpoint_add_empty_body_400(client, session):
    _event(session, "evt-1")
    session.commit()
    resp = client.post(
        "/api/v1/shift-handover/notes",
        json={"event_key": "evt-1", "body": "   "},
    )
    assert resp.status_code == 400


def test_endpoint_summary(client, session):
    _event(session, "evt-1")
    client.post(
        "/api/v1/shift-handover/notes",
        json={"event_key": "evt-1", "body": "özet notu"},
    )
    resp = client.get("/api/v1/shift-handover")
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_count"] == 1
    assert any(e["category"] == NOTE_CATEGORY for e in body["chronology"])


def test_endpoint_delete(client, session):
    _event(session, "evt-1")
    session.commit()
    created = client.post(
        "/api/v1/shift-handover/notes",
        json={"event_key": "evt-1", "body": "silinecek"},
    ).json()
    resp = client.delete(f"/api/v1/shift-handover/notes/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert client.get("/api/v1/shift-handover/notes").json()["count"] == 0
