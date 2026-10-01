"""Chronological operator event timeline (EM-081, Epic E8).

At shift handover the operator has to narrate *what happened* in order. The
pieces already exist but live in two places: the live change feed (EM-090)
records fire-event / forecast / alert updates, while operator-accepted
recommendations are immutable audit rows written by EM-047. Neither view shows
the other, and neither is a single time-ordered stream the operator can scroll
through (EM-081 acceptance: "every event - forecast update, accepted
recommendation, alert - is shown in a chronological stream").

This service merges both into one **read-time projection** - nothing new is
written and no table/migration is added (``persistence`` is ``none``). Each
source row becomes a timeline entry carrying a stable ``category`` (with a
Turkish label), the incident ``event_key`` and its UTC timestamp; the merged
list is ordered newest-first with a deterministic tie-break so two runs over the
same data always produce the same stream.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.live import LiveUpdate
from src.models.recommendation import RecommendationDecision
from src.utils.timeutils import to_utc_iso, utc_now

# Timeline categories. The first three mirror the live-feed kinds (EM-090);
# ``accepted_recommendation`` is derived from EM-047 audit rows whose action
# commits an assignment. Reject/release are *not* "accepted" so they stay out.
TIMELINE_CATEGORIES = (
    "fire_event",
    "forecast",
    "alert",
    "accepted_recommendation",
)
CATEGORY_LABELS = {
    "fire_event": "Yangın olayı",
    "forecast": "Tahmin güncellemesi",
    "alert": "Uyarı",
    "accepted_recommendation": "Kabul edilen öneri",
}

# Actions that mean the operator accepted (or edited-then-accepted) a proposal.
_ACCEPTING_ACTIONS = ("accept", "edit")

# A deterministic cross-source tie-break: when two entries share a timestamp,
# this rank decides their relative order (lower rank first within the newest
# block) so the stream is stable regardless of insertion interleaving.
_TABLE_RANK = {"live_updates": 0, "recommendation_decisions": 1}

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

TIMELINE_ATTRIBUTION = (
    "EM-081: olay zaman çizelgesi canlı akış (olay/tahmin/uyarı) + kabul edilen "
    "öneri denetim kayıtlarından tek kronolojik akışta birleştirilir"
)
TIMELINE_PERSISTENCE = "none"


def _default_limit(settings: Any) -> int:
    return int(getattr(settings, "EVENT_TIMELINE_DEFAULT_LIMIT", DEFAULT_LIMIT))


def _max_limit(settings: Any) -> int:
    return int(getattr(settings, "EVENT_TIMELINE_MAX_LIMIT", MAX_LIMIT))


def _resolve_limit(settings: Any, limit: Optional[int]) -> int:
    """Clamp the requested page size into ``[1, MAX_LIMIT]`` (default when None)."""
    maximum = _max_limit(settings)
    if limit is None:
        return max(1, min(_default_limit(settings), maximum))
    try:
        want = int(limit)
    except (TypeError, ValueError):
        want = _default_limit(settings)
    return max(1, min(want, maximum))


def _opt_str(value: Any) -> Optional[str]:
    """Normalise an ORM string column (or ``None``) to ``str | None``."""
    if value is None:
        return None
    text = str(value)
    return text or None


def _entry(
    *,
    category: str,
    event_key: Optional[str],
    title: str,
    detail: Optional[str],
    source: Optional[str],
    at: Any,
    table: str,
    row_id: int,
) -> dict[str, Any]:
    """Build one normalised timeline entry (raw ``at`` kept for sorting)."""
    return {
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "event_key": event_key,
        "title": title,
        "detail": detail,
        "source": source,
        "at": at,
        "ref": {"table": table, "id": row_id},
    }


def _live_entries(session: Session, cap: int) -> list[dict[str, Any]]:
    """Newest ``cap`` live-feed rows mapped to timeline entries."""
    entries: list[dict[str, Any]] = []
    rows = session.scalars(
        select(LiveUpdate).order_by(LiveUpdate.id.desc()).limit(cap)
    ).all()
    for row in rows:
        category = str(row.kind)
        if category not in CATEGORY_LABELS:
            continue
        entries.append(
            _entry(
                category=category,
                event_key=_opt_str(row.event_key),
                title=str(row.title or CATEGORY_LABELS[category]),
                detail=_opt_str(row.message),
                source=_opt_str(row.source),
                at=row.created_at,
                table="live_updates",
                row_id=int(row.id),
            )
        )
    return entries


def _decision_entries(session: Session, cap: int) -> list[dict[str, Any]]:
    """Newest ``cap`` *accepted* recommendations mapped to timeline entries."""
    entries: list[dict[str, Any]] = []
    rows = session.scalars(
        select(RecommendationDecision)
        .where(RecommendationDecision.action.in_(_ACCEPTING_ACTIONS))
        .order_by(RecommendationDecision.id.desc())
        .limit(cap)
    ).all()
    for row in rows:
        verb = "düzenlenerek kabul edildi" if row.action == "edit" else "kabul edildi"
        title = f"{row.resource_key} {verb}"
        entries.append(
            _entry(
                category="accepted_recommendation",
                event_key=_opt_str(row.event_key),
                title=title,
                detail=_opt_str(row.reason),
                source=_opt_str(row.decided_by),
                at=row.created_at,
                table="recommendation_decisions",
                row_id=int(row.id),
            )
        )
    return entries


def _serialize(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the API-friendly form (drops the raw datetime used for sorting)."""
    at = entry["at"]
    return {
        "category": entry["category"],
        "category_label": entry["category_label"],
        "event_key": entry["event_key"],
        "title": entry["title"],
        "detail": entry["detail"],
        "source": entry["source"],
        "at": to_utc_iso(at) if isinstance(at, datetime) else None,
        "ref": entry["ref"],
    }


def _sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Newest-first, then table rank, then id - fully deterministic."""
    at = entry["at"]
    # Normalise the sort instant; missing timestamps sort oldest so they never
    # masquerade as the newest event at the top of the stream.
    stamp = at if isinstance(at, datetime) else datetime.min
    return (stamp, _TABLE_RANK.get(entry["ref"]["table"], 99), entry["ref"]["id"])


def event_timeline(
    session: Session,
    settings: Any,
    *,
    event_key: Optional[str] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Merge the live feed and accepted recommendations into one time stream.

    Both sources are queried for their newest ``cap`` rows (``cap`` bounds the
    merged page), normalised, sorted newest-first and then filtered by the
    optional ``event_key`` / ``category`` before the final ``limit`` slice. An
    unknown ``category`` is not swallowed silently: ``filter`` comes back ``None``
    while ``requested_filter`` preserves the raw value and the unfiltered stream
    is returned (mirrors the EM-078 band-filter contract).
    """
    resolved = _resolve_limit(settings, limit)
    # Fetch each source's newest ``MAX_LIMIT`` rows so a small page size (or an
    # event/category filter) still has the full recent window to draw from.
    cap = _max_limit(settings)
    entries = _live_entries(session, cap) + _decision_entries(session, cap)
    entries.sort(key=_sort_key, reverse=True)

    category_filter = category.strip().lower() if category else None
    valid_category = category_filter in TIMELINE_CATEGORIES

    stream = entries
    if event_key:
        stream = [e for e in stream if e["event_key"] == event_key]
    if valid_category:
        stream = [e for e in stream if e["category"] == category_filter]

    page = stream[:resolved]

    counts = {cat: 0 for cat in TIMELINE_CATEGORIES}
    for entry in stream:
        counts[entry["category"]] += 1

    return {
        "panel": "event_timeline",
        "count": len(page),
        "total_matching": len(stream),
        "filter": {
            "event_key": event_key,
            "category": category_filter if valid_category else None,
            "requested_category": category_filter,
        },
        "category_counts": counts,
        "limit": resolved,
        "max_limit": _max_limit(settings),
        "entries": [_serialize(e) for e in page],
        "generated_at": to_utc_iso(utc_now()),
        "attribution": TIMELINE_ATTRIBUTION,
        "persistence": TIMELINE_PERSISTENCE,
    }


def timeline_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: categories, labels and the merge/ordering contract."""
    return {
        "categories": [
            {"code": code, "label": CATEGORY_LABELS[code]}
            for code in TIMELINE_CATEGORIES
        ],
        "sources": [
            "live_updates (fire_event/forecast/alert, EM-090)",
            "recommendation_decisions (accept/edit, EM-047)",
        ],
        "default_limit": _default_limit(settings),
        "max_limit": _max_limit(settings),
        "sort": "at desc, source-rank, id desc",
        "attribution": TIMELINE_ATTRIBUTION,
        "persistence": TIMELINE_PERSISTENCE,
    }


__all__ = [
    "CATEGORY_LABELS",
    "TIMELINE_ATTRIBUTION",
    "TIMELINE_CATEGORIES",
    "TIMELINE_PERSISTENCE",
    "event_timeline",
    "timeline_config",
]
