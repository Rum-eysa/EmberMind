"""Multi-fire management survey and cross-fire conflict warnings (EM-082, E8).

A coordinator runs several fires at once and has to spread a shared pool of
suppression units between them (EM-082 acceptance: "several fires are monitored
at the same time; conflicts are warned when resources are shared between
fires"). The pieces already exist but are scattered: ``FireEvent`` rows carry
the active incidents, ``SuppressionResource`` rows carry each unit's live
status, and the EM-047/EM-053 decision audit carries which incident a busy unit
is currently committed to. No single view answers "how many fires are live, who
is assigned where, and where does the allocation conflict?".

This service is a **read-time projection** (``persistence`` is ``none`` - no new
table, no migration). For every *active* fire it builds the roster of units
currently committed to it (reusing the same "newest accept/edit audit row while
still busy" rule the EM-053 double-booking guard applies), then surfaces the
cross-fire conflicts a coordinator must act on:

* ``orphaned_units`` - a unit still flagged busy (``en_route`` / ``deployed``)
  whose current assignment points at an incident that is no longer active. It is
  spoken for but not actually helping any live fire, so it should be released.
* ``contended_bases`` - a home base whose committed units are stretched across
  two or more *simultaneous* active fires. The same pool is being shared, so a
  further commitment from that base is a real trade-off, not free capacity.
* ``understaffed_critical`` - an active fire rated ``high`` / ``critical`` that
  currently has no committed unit while other fires are being served. This is
  the "balance the resources between fires" half of the user story.

The whole thing is deterministic: rosters are ordered, conflicts are keyed and
sorted, so two runs over the same data always produce the same survey.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.inventory import SuppressionResource
from src.models.recommendation import RecommendationDecision
from src.models.spatial import FireEvent
from src.utils.timeutils import to_utc_iso, utc_now

# Statuses that mean a unit is spoken for (EM-031 vocabulary; same set the
# EM-053 guard treats as "already booked").
_BUSY_STATUSES = frozenset({"en_route", "deployed"})

# Audit actions that commit an assignment (a later ``release`` frees it). EM-053
# derives the current booking from the newest of these.
_ASSIGN_ACTIONS = ("accept", "edit")

# Severity ranking for the survey ordering and the understaffed check. Higher
# rank = more urgent. Anything unknown ranks lowest so it never outranks a known
# severity. SEVERITY_ORDER is the same set ordered most-to-least urgent for the
# descriptive config payload.
_SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
SEVERITY_ORDER = ("critical", "high", "medium", "low")
# Severities at or above this rank are "urgent" for the understaffed warning.
_CRITICAL_RANK = 2

MAX_EVENTS = 50

MULTI_FIRE_ATTRIBUTION = (
    "EM-082: çoklu yangın yönetimi - aktif yangınlar ve bunlara konuşlanan "
    "kaynaklar okuma zamanı derlenir; kaynaklar yangınlar arasında paylaşıldığında "
    "çakışmalar uyarılır"
)
MULTI_FIRE_PERSISTENCE = "none"


def _opt_str(value: Any) -> Optional[str]:
    """Normalise an ORM string column (or ``None``) to ``str | None``."""
    if value is None:
        return None
    text = str(value)
    return text or None


def _rank(severity: Any) -> int:
    """Map a severity string to its urgency rank (unknown -> lowest)."""
    return _SEVERITY_RANK.get(str(severity).strip().lower(), 0)


def _max_events(settings: Any) -> int:
    return int(getattr(settings, "MULTI_FIRE_MAX_EVENTS", MAX_EVENTS))


def _clamp_count(value: Any, default: int) -> int:
    """Coerce a settings value to a positive int, falling back to the default."""
    try:
        want = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, want)


def _active_events(session: Session, limit: int) -> list[FireEvent]:
    """Active fire events, most urgent first then oldest-starting first."""
    rows = session.scalars(select(FireEvent)).all()
    active = [row for row in rows if str(row.status) == "active"]
    active.sort(key=lambda r: (-_rank(r.severity), str(r.started_at), r.event_key))
    return active[:limit]


def _busy_resources(session: Session) -> list[SuppressionResource]:
    """Units currently flagged busy (``en_route`` / ``deployed``)."""
    rows = session.scalars(
        select(SuppressionResource).where(
            SuppressionResource.status.in_(tuple(sorted(_BUSY_STATUSES)))
        )
    ).all()
    return list(rows)


def _newest_assignment_rows(
    session: Session, resource_keys: list[str]
) -> dict[str, RecommendationDecision]:
    """Newest audit row per busy resource (whatever the action).

    Mirrors the EM-053 rule that a booking is only active while the newest
    decision is an ``accept``/``edit`` - a later ``release`` wins and is simply
    not an assignment. Iterating newest-first, the first row seen per resource
    is its newest.
    """
    if not resource_keys:
        return {}
    rows = session.scalars(
        select(RecommendationDecision)
        .where(RecommendationDecision.resource_key.in_(resource_keys))
        .order_by(RecommendationDecision.id.desc())
    ).all()
    newest: dict[str, RecommendationDecision] = {}
    for row in rows:
        key = str(row.resource_key)
        if key not in newest:
            newest[key] = row
    return newest


def _unit_payload(
    resource: SuppressionResource, assigned_event: Optional[str]
) -> dict[str, Any]:
    """One committed unit as shown in a fire's roster."""
    return {
        "resource_key": str(resource.resource_key),
        "name": str(resource.name),
        "resource_type": str(resource.resource_type),
        "status": str(resource.status),
        "base_key": _opt_str(resource.base_key),
        "country": _opt_str(resource.country),
        "assigned_event": assigned_event,
    }


def multi_fire_overview(
    session: Session, settings: Any, *, event_key: Optional[str] = None
) -> dict[str, Any]:
    """Survey all active fires, their committed units and the cross-fire conflicts.

    Returns per-event rosters (ordered), pool totals and three conflict buckets.
    An optional ``event_key`` scopes the returned ``events`` list to one incident
    but keeps the conflict survey global (a shared base / orphan is a whole-pool
    concern); the scoping never hides a conflict that touches the selected fire.
    """
    limit = _clamp_count(_max_events(settings), MAX_EVENTS)
    events = _active_events(session, limit)
    active_keys = {str(e.event_key) for e in events}

    busy = _busy_resources(session)
    newest = _newest_assignment_rows(session, [str(r.resource_key) for r in busy])

    # Resolve each busy unit's live assignment (event_key only if newest row is
    # an accept/edit). ``None`` provenance is never asserted as a booking.
    assignment: dict[str, Optional[str]] = {}
    decision_key_of: dict[str, str] = {}
    for resource in busy:
        rk = str(resource.resource_key)
        row = newest.get(rk)
        if row is not None and row.action in _ASSIGN_ACTIONS:
            assignment[rk] = _opt_str(row.event_key)
            decision_key_of[rk] = str(row.decision_key)
        else:
            assignment[rk] = None

    # Build per-active-fire rosters from units assigned to that fire.
    rosters: dict[str, list[dict[str, Any]]] = {k: [] for k in active_keys}
    orphaned_units: list[dict[str, Any]] = []
    for resource in busy:
        rk = str(resource.resource_key)
        assigned = assignment.get(rk)
        if assigned is None:
            # Busy but provenance-blind (no recorded incident) - not an
            # actionable conflict, so it is simply left out of every roster.
            continue
        if assigned in active_keys:
            rosters[assigned].append(_unit_payload(resource, assigned))
        else:
            orphaned_units.append(
                {
                    **_unit_payload(resource, assigned),
                    "reason": "kaynak meşgul görünüyor ancak atandığı olay aktif "
                    "değil; serbest bırakılıp yeniden konuşlandırılabilir",
                }
            )

    for units in rosters.values():
        units.sort(key=lambda u: (u["resource_type"], u["resource_key"]))
    orphaned_units.sort(key=lambda u: u["resource_key"])

    # Contended bases: a home base committed across >=2 simultaneous active fires.
    base_to_events: dict[str, set[str]] = {}
    base_to_units: dict[str, set[str]] = {}
    for event in events:
        ek = str(event.event_key)
        for unit in rosters[ek]:
            bk = unit["base_key"]
            if not bk:
                continue
            base_to_events.setdefault(bk, set()).add(ek)
            base_to_units.setdefault(bk, set()).add(unit["resource_key"])
    contended_bases = [
        {
            "base_key": bk,
            "events": sorted(base_to_events[bk]),
            "resource_keys": sorted(base_to_units[bk]),
            "reason": "aynı üs birden çok aktif yangına kaynak veriyor; bu "
            "havuz paylaşımlıdır",
        }
        for bk in sorted(base_to_events)
        if len(base_to_events[bk]) >= 2
    ]

    # Understaffed urgent fires: high/critical severity with no committed unit.
    understaffed_critical = [
        {
            "event_key": str(event.event_key),
            "name": str(event.name),
            "severity": str(event.severity),
            "reason": "acil (yüksek/kritik) bir aktif yangına henüz kaynak "
            "konuşlanmamış; havuzu yeniden dengeleyin",
        }
        for event in events
        if _rank(event.severity) >= _CRITICAL_RANK
        and len(rosters[str(event.event_key)]) == 0
    ]

    available_units = len(
        session.scalars(
            select(SuppressionResource).where(SuppressionResource.status == "available")
        ).all()
    )

    event_rows = [
        {
            "event_key": str(event.event_key),
            "name": str(event.name),
            "severity": str(event.severity),
            "severity_rank": _rank(event.severity),
            "status": str(event.status),
            "started_at": to_utc_iso(event.started_at)
            if isinstance(event.started_at, datetime)
            else None,
            "committed": rosters[str(event.event_key)],
            "committed_count": len(rosters[str(event.event_key)]),
        }
        for event in events
    ]

    conflict_count = (
        len(orphaned_units) + len(contended_bases) + len(understaffed_critical)
    )

    shown_events = event_rows
    if event_key:
        shown_events = [row for row in event_rows if row["event_key"] == event_key]

    return {
        "panel": "multi_fire",
        "events": shown_events,
        "event_count": len(shown_events),
        "active_event_total": len(event_rows),
        "filter": {"event_key": event_key},
        "totals": {
            "active_events": len(event_rows),
            "busy_units": len(busy),
            "committed_units": sum(len(v) for v in rosters.values()),
            "available_units": available_units,
        },
        "conflicts": {
            "orphaned_units": orphaned_units,
            "contended_bases": contended_bases,
            "understaffed_critical": understaffed_critical,
        },
        "conflict_count": conflict_count,
        "has_conflicts": conflict_count > 0,
        "max_events": limit,
        "generated_at": to_utc_iso(utc_now()),
        "attribution": MULTI_FIRE_ATTRIBUTION,
        "persistence": MULTI_FIRE_PERSISTENCE,
    }


def multi_fire_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: severities, statuses, conflict taxonomy and bounds."""
    return {
        "severities": [
            {"code": code, "rank": _SEVERITY_RANK[code]} for code in SEVERITY_ORDER
        ],
        "busy_statuses": sorted(_BUSY_STATUSES),
        "conflict_types": [
            "orphaned_units",
            "contended_bases",
            "understaffed_critical",
        ],
        "sources": [
            "fire_events (active, EM-005)",
            "suppression_resources (status, EM-008)",
            "recommendation_decisions (accept/edit assignment, EM-047/EM-053)",
        ],
        "max_events": _clamp_count(_max_events(settings), MAX_EVENTS),
        "attribution": MULTI_FIRE_ATTRIBUTION,
        "persistence": MULTI_FIRE_PERSISTENCE,
    }


__all__ = [
    "MAX_EVENTS",
    "MULTI_FIRE_ATTRIBUTION",
    "MULTI_FIRE_PERSISTENCE",
    "SEVERITY_ORDER",
    "multi_fire_config",
    "multi_fire_overview",
]
