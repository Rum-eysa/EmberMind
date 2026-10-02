"""Shift-handover notes and one-click handover summary (EM-089, Epic E8).

At the end of a shift the operator has to hand the incident over to the next
crew. Everything the machine knows is already streamable (live feed EM-090,
accepted recommendations EM-047, chronological timeline EM-081, multi-fire
roster EM-082), but two things are missing and they are exactly what EM-089
asks for:

* the operator cannot type a *free-text note* against an incident and have it
  survive the shift (the persisted :class:`EventNote` surface closes this);
* there is no *one-click handover summary* that folds the human commentary
  together with the machine view of each active fire into a single narrative the
  next crew can read top-to-bottom.

This service owns both. Notes are the only thing it writes; the summary is a
**read-time projection** that composes, for every active fire, its committed
resource roster (via :func:`multi_fire_overview`), its slice of the chronological
event stream (via :func:`event_timeline`) and the operator's own notes, merged
newest-first. Nothing from EM-081/EM-082 is duplicated or mutated - their
categories and tests are untouched; notes simply join the narrative here.

Everything is deterministic: notes are ordered by their monotonic id, the merged
chronology is sorted timestamp-desc then id-desc, and unknown incidents raise
rather than being silently dropped.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.event_notes import EventNote
from src.models.spatial import FireEvent
from src.services.event_timeline import event_timeline
from src.services.multi_fire import multi_fire_overview
from src.utils.timeutils import to_utc_iso, utc_now

# Timeline category the operator's own notes carry inside the merged chronology.
# It lives only here - EM-081's own category set is deliberately not extended.
NOTE_CATEGORY = "operator_note"
NOTE_LABEL = "Operatör notu"

DEFAULT_MAX_NOTES = 100

HANDOVER_ATTRIBUTION = (
    "EM-089: vardiya devri - olaya serbest metin not eklenir, notlar zaman "
    "çizelgesi akışında görünür ve tek tıkla vardiya devri özeti üretilir"
)
HANDOVER_PERSISTENCE = "event_notes"


class ShiftHandoverError(Exception):
    """Raised for an unknown incident, an empty note or a missing note id."""


def _clamp_count(value: Any, default: int) -> int:
    """Coerce a settings value to a positive int, falling back to the default."""
    try:
        want = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, want)


def _max_notes(settings: Any) -> int:
    return _clamp_count(
        getattr(settings, "SHIFT_HANDOVER_MAX_NOTES", DEFAULT_MAX_NOTES),
        DEFAULT_MAX_NOTES,
    )


def _opt_str(value: Any) -> Optional[str]:
    """Normalise an ORM string column (or ``None``) to ``str | None``."""
    if value is None:
        return None
    text = str(value)
    return text or None


def _event_exists(session: Session, event_key: str) -> bool:
    """Whether a fire event with this key is present."""
    row = session.scalars(
        select(FireEvent.id).where(FireEvent.event_key == event_key)
    ).first()
    return row is not None


def _require_event(session: Session, event_key: str) -> str:
    """Validate the incident exists, else raise (unknown keys never stored)."""
    key = (event_key or "").strip()
    if not key:
        raise ShiftHandoverError("event_key boş olamaz")
    if not _event_exists(session, key):
        raise ShiftHandoverError(f"fire event {key} not found")
    return key


def add_note(
    session: Session,
    settings: Any,
    *,
    event_key: str,
    body: str,
    author: Optional[str] = None,
) -> dict[str, Any]:
    """Attach a free-text note to an incident (EM-089 acceptance #1).

    The note is stored trimmed but non-empty; an unknown ``event_key`` raises so
    a stray note can never orphan against a non-existent incident.
    """
    key = _require_event(session, event_key)
    text = (body or "").strip()
    if not text:
        raise ShiftHandoverError("not boş olamaz")
    row = EventNote(
        event_key=key,
        body=text,
        author=_opt_str((author or "").strip()),
    )
    session.add(row)
    session.flush()
    return dict(row.as_dict)


def list_notes(
    session: Session,
    settings: Any,
    *,
    event_key: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Return the operator's notes, newest-first, optionally scoped to one fire.

    ``event_key`` filters to a single incident; ``limit`` clamps the page into
    ``[1, SHIFT_HANDOVER_MAX_NOTES]``. The ``note_count`` in the payload always
    describes the whole (post-filter) set so the panel badge never lies.
    """
    cap = _max_notes(settings)
    query = select(EventNote).order_by(EventNote.id.desc())
    if event_key:
        query = query.where(EventNote.event_key == event_key)
    rows = list(session.scalars(query).all())
    total = len(rows)
    resolved = cap if limit is None else _clamp_count(limit, cap)
    page = rows[: max(1, min(resolved, cap))]
    return {
        "panel": "event_notes",
        "filter": {"event_key": event_key},
        "count": len(page),
        "total_matching": total,
        "max_notes": cap,
        "notes": [dict(row.as_dict) for row in page],
        "generated_at": to_utc_iso(utc_now()),
        "attribution": HANDOVER_ATTRIBUTION,
        "persistence": HANDOVER_PERSISTENCE,
    }


def get_note(session: Session, note_id: int) -> dict[str, Any]:
    """Fetch a single note by id (raises when missing)."""
    row = session.get(EventNote, int(note_id))
    if row is None:
        raise ShiftHandoverError(f"not bulunamadı: {note_id}")
    return dict(row.as_dict)


def delete_note(session: Session, note_id: int) -> dict[str, Any]:
    """Remove one note (returns the deleted id; raises when missing)."""
    row = session.get(EventNote, int(note_id))
    if row is None:
        raise ShiftHandoverError(f"not bulunamadı: {note_id}")
    deleted = int(row.id)
    session.delete(row)
    session.flush()
    return {"deleted": deleted}


def _active_events(session: Session) -> list[FireEvent]:
    """Active incidents, most severe first then oldest-start, for the summary."""
    rows = list(session.scalars(select(FireEvent)).all())
    active = [row for row in rows if str(row.status) == "active"]
    active.sort(key=lambda r: (str(r.started_at), str(r.event_key)))
    return active


def _chronology(
    session: Session, settings: Any, event_key: Optional[str]
) -> list[dict[str, Any]]:
    """Merge EM-081's timeline with this incident's notes, newest-first.

    This is the concrete answer to EM-089 acceptance #2 ("notes are visible on
    the timeline"): the operator's free-text notes join the machine event stream
    in one chronological list, without altering EM-081's own projection.
    """
    feed = event_timeline(session, settings, event_key=event_key, limit=None)
    entries: list[dict[str, Any]] = []
    for item in feed["entries"]:
        entries.append(
            {
                "kind": "event",
                "category": item["category"],
                "label": item["category_label"],
                "event_key": item["event_key"],
                "text": item["title"],
                "detail": item["detail"],
                "at": item["at"],
                "ref_id": item["ref"]["id"],
            }
        )
    note_query = select(EventNote).order_by(EventNote.id.desc())
    if event_key:
        note_query = note_query.where(EventNote.event_key == event_key)
    for row in session.scalars(note_query).all():
        entries.append(
            {
                "kind": "note",
                "category": NOTE_CATEGORY,
                "label": NOTE_LABEL,
                "event_key": str(row.event_key),
                "text": str(row.body),
                "detail": _opt_str(row.author),
                "at": to_utc_iso(row.created_at),
                "ref_id": int(row.id),
            }
        )
    entries.sort(key=_chrono_sort_key, reverse=True)
    return entries


def _chrono_sort_key(entry: dict[str, Any]) -> tuple[Any, int]:
    """Sort by ISO timestamp then note/event id; missing stamps sink oldest."""
    at = entry.get("at")
    stamp = at if isinstance(at, str) else ""
    return (stamp, int(entry.get("ref_id") or 0))


def handover_summary(
    session: Session, settings: Any, *, event_key: Optional[str] = None
) -> dict[str, Any]:
    """One-click shift-handover summary (EM-089 acceptance #3).

    Folds the machine view (per-fire committed roster from EM-082, cross-fire
    conflicts, merged chronology with notes) into a single narrative the next
    crew can read top-to-bottom. ``event_key`` scopes the incident cards and the
    chronology to one fire; the conflict tally stays whole-pool because a shared
    base is a handover concern regardless of which card you are reading.
    """
    events = _active_events(session)
    overview = multi_fire_overview(session, settings)
    committed_by_event = {
        str(row["event_key"]): int(row["committed_count"]) for row in overview["events"]
    }
    notes_by_event: dict[str, list[dict[str, Any]]] = {}
    all_notes = session.scalars(select(EventNote).order_by(EventNote.id.desc())).all()
    for row in all_notes:
        notes_by_event.setdefault(str(row.event_key), []).append(dict(row.as_dict))

    cards: list[dict[str, Any]] = []
    for event in events:
        ek = str(event.event_key)
        if event_key and ek != event_key:
            continue
        event_notes = notes_by_event.get(ek, [])
        cards.append(
            {
                "event_key": ek,
                "name": str(event.name),
                "severity": str(event.severity),
                "status": str(event.status),
                "started_at": to_utc_iso(event.started_at)
                if isinstance(event.started_at, datetime)
                else None,
                "committed_count": committed_by_event.get(ek, 0),
                "note_count": len(event_notes),
                "latest_note": event_notes[0]["body"] if event_notes else None,
            }
        )

    chronology = _chronology(session, settings, event_key)
    conflicts = overview["conflicts"]
    shown_notes = [e for e in chronology if e["kind"] == "note"]

    return {
        "panel": "shift_handover",
        "filter": {"event_key": event_key},
        "generated_at": to_utc_iso(utc_now()),
        "incident_count": len(cards),
        "incidents": cards,
        "note_count": len(all_notes),
        "notes_in_view": len(shown_notes),
        "chronology": chronology,
        "conflicts": {
            "orphaned_units": len(conflicts["orphaned_units"]),
            "contended_bases": len(conflicts["contended_bases"]),
            "understaffed_critical": len(conflicts["understaffed_critical"]),
            "total": overview["conflict_count"],
        },
        "attribution": HANDOVER_ATTRIBUTION,
        "persistence": HANDOVER_PERSISTENCE,
    }


def handover_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: sources, the note category and the page bounds."""
    return {
        "note_category": NOTE_CATEGORY,
        "note_label": NOTE_LABEL,
        "max_notes": _max_notes(settings),
        "sources": [
            "event_notes (free-text, EM-089)",
            "event_timeline (chronology merge, EM-081)",
            "multi_fire (roster + conflicts, EM-082)",
            "fire_events (active incidents, EM-005)",
        ],
        "attribution": HANDOVER_ATTRIBUTION,
        "persistence": HANDOVER_PERSISTENCE,
    }


__all__ = [
    "DEFAULT_MAX_NOTES",
    "HANDOVER_ATTRIBUTION",
    "HANDOVER_PERSISTENCE",
    "NOTE_CATEGORY",
    "NOTE_LABEL",
    "ShiftHandoverError",
    "add_note",
    "delete_note",
    "get_note",
    "handover_config",
    "handover_summary",
    "list_notes",
]
