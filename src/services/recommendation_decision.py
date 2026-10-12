"""Operator accept / reject / edit workflow for positioning proposals
(EM-047, Epic E5).

The engine proposes (EM-052); the operator disposes. This service turns one
proposal into one durable decision:

* ``accept`` commits the proposed resource by moving it to the ``en_route``
  ("yolda") status (EM-031 vocabulary) and writes an audit row.
* ``edit`` is an accept with operator-supplied overrides (e.g. a corrected
  arrival ETA); it also commits to ``en_route`` and records the edits.
* ``reject`` leaves the resource untouched and records an *optional* reason.

The decision is always persisted, so the audit trail (criterion: "Her karar
denetim kaydına yazılır") is complete regardless of the action taken. Status
transitions reuse the inventory service so the shared vocabulary and ETA
validation stay in one place.
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.inventory import SuppressionResource
from src.models.recommendation import DECISION_ACTIONS, RecommendationDecision
from src.models.spatial import FireEvent
from src.services.inventory import get_resource, update_resource

# Committing status applied by an accept / edit (EM-031 "yolda").
_COMMIT_STATUS = "en_route"

# Statuses that mean a unit is already spoken for (EM-053 double-booking guard).
_BUSY_STATUSES = frozenset({"en_route", "deployed"})

# Audit actions that commit an assignment (versus a later ``release`` that frees
# it). EM-053 derives the current booking from the newest of these.
_ASSIGN_ACTIONS = ("accept", "edit")


class DecisionError(RuntimeError):
    """Raised for an invalid decision (unknown action, missing resource)."""


class ConflictError(RuntimeError):
    """Raised when accepting a unit already assigned to a different incident
    (EM-053: a resource may serve only one task at a time)."""


def _new_key() -> str:
    """A short, URL-safe unique decision key (collision probability negligible)."""
    return f"dec-{secrets.token_hex(6)}"


def _clean(value: Any, maximum: int) -> str | None:
    """Trim an optional free-text field to ``None`` or a bounded string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:maximum]


def _latest_decision_row(
    session: Session, resource_key: str
) -> RecommendationDecision | None:
    """Newest audit row for one resource, whatever the action."""
    return session.scalar(
        select(RecommendationDecision)
        .where(RecommendationDecision.resource_key == resource_key)
        .order_by(RecommendationDecision.id.desc())
        .limit(1)
    )


def _active_assignment_event(
    session: Session, resource: SuppressionResource
) -> str | None:
    """Incident a busy unit is currently committed to (EM-053).

    A booking is active only while the resource is still ``en_route`` /
    ``deployed`` *and* its newest audit row is an ``accept``/``edit`` (a later
    ``release`` clears it). Returns ``None`` when the unit is free or was
    committed without a recorded incident, so the guard never blocks on
    provenance it cannot see.
    """
    if str(resource.status) not in _BUSY_STATUSES:
        return None
    row = _latest_decision_row(session, str(resource.resource_key))
    if row is None or row.action not in _ASSIGN_ACTIONS:
        return None
    return str(row.event_key) if row.event_key else None


def record_decision(
    session: Session,
    *,
    resource_key: str,
    action: str,
    event_key: str | None = None,
    proposal_id: str | None = None,
    reason: str | None = None,
    decided_by: str | None = None,
    detail: dict[str, Any] | None = None,
    arrival_minutes: Any = None,
) -> dict[str, Any]:
    """Record one operator decision and apply its status effect.

    Returns the persisted decision plus the resource status before/after.
    Raises :class:`DecisionError` for an unknown action or resource. A reject
    never changes the resource; an accept/edit commits it to ``en_route`` and
    may schedule an arrival ETA when ``arrival_minutes`` is supplied.
    """
    if action not in DECISION_ACTIONS:
        raise DecisionError(
            f"invalid action {action!r}; expected one of {list(DECISION_ACTIONS)}"
        )
    resource = get_resource(session, resource_key)
    if resource is None:
        raise DecisionError(f"resource '{resource_key}' not found")

    # EM-053: a unit committed to one incident cannot be booked for another.
    if action in _ASSIGN_ACTIONS and event_key:
        assigned = _active_assignment_event(session, resource)
        if assigned is not None and assigned != str(event_key):
            raise ConflictError(
                f"resource '{resource_key}' is already assigned to incident "
                f"'{assigned}' ({resource.status}); release it before assigning "
                f"it to '{event_key}'"
            )

    status_before = str(resource.status)
    status_after = status_before
    if action in ("accept", "edit"):
        changes: dict[str, Any] = {"status": _COMMIT_STATUS}
        if arrival_minutes is not None and arrival_minutes != "":
            changes["arrival_minutes"] = arrival_minutes
        updated = update_resource(session, resource_key, changes)
        status_after = str(updated.status)

    snapshot: dict[str, Any] = dict(detail or {})
    snapshot["action"] = action
    if proposal_id is not None:
        snapshot.setdefault("proposal_id", proposal_id)
    if arrival_minutes is not None and arrival_minutes != "":
        snapshot["arrival_minutes"] = arrival_minutes

    row = RecommendationDecision(
        decision_key=_new_key(),
        event_key=_clean(event_key, 64),
        proposal_id=_clean(proposal_id, 96),
        resource_key=resource_key,
        action=action,
        reason=_clean(reason, 255),
        decided_by=_clean(decided_by, 64),
        detail_json=json.dumps(snapshot, default=str),
        resource_status_before=status_before,
        resource_status_after=status_after,
    )
    session.add(row)
    session.flush()
    return {
        "decision": row.as_dict,
        "resource_status_before": status_before,
        "resource_status_after": status_after,
        "status_changed": status_before != status_after,
    }


def list_decisions(
    session: Session,
    *,
    event_key: str | None = None,
    resource_key: str | None = None,
    action: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recorded decisions (newest first), optionally filtered."""
    query = select(RecommendationDecision).order_by(RecommendationDecision.id.desc())
    if event_key:
        query = query.where(RecommendationDecision.event_key == event_key)
    if resource_key:
        query = query.where(RecommendationDecision.resource_key == resource_key)
    if action:
        query = query.where(RecommendationDecision.action == action)
    rows = session.scalars(query.limit(max(1, int(limit)))).all()
    return [row.as_dict for row in rows]


def get_decision(session: Session, decision_key: str) -> dict[str, Any]:
    """Fetch one decision by its key, or raise :class:`DecisionError`."""
    row = session.scalar(
        select(RecommendationDecision).where(
            RecommendationDecision.decision_key == decision_key
        )
    )
    if row is None:
        raise DecisionError(f"decision '{decision_key}' not found")
    return row.as_dict


def release_assignment(
    session: Session,
    *,
    resource_key: str,
    event_key: str | None = None,
    decided_by: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Free a committed unit back to ``available`` (EM-053 task completion).

    Releasing an idle unit is a harmless no-op (``released: False``); releasing
    a booked one clears its status and scheduled arrival ETA and writes a
    ``release`` audit row, so the double-booking guard stops seeing it. When
    ``event_key`` is supplied it must match the current booking, preventing a
    coordinator from freeing a unit another incident is relying on.
    """
    resource = get_resource(session, resource_key)
    if resource is None:
        raise DecisionError(f"resource '{resource_key}' not found")

    status_before = str(resource.status)
    assigned = _active_assignment_event(session, resource)
    if status_before not in _BUSY_STATUSES:
        return {
            "released": False,
            "reason": "not_assigned",
            "resource_status": status_before,
            "status_changed": False,
            "decision": None,
        }
    if event_key and assigned is not None and str(event_key) != assigned:
        raise ConflictError(
            f"resource '{resource_key}' is assigned to '{assigned}', "
            f"not '{event_key}'"
        )

    updated = update_resource(
        session, resource_key, {"status": "available", "arrival_minutes": None}
    )
    status_after = str(updated.status)
    row = RecommendationDecision(
        decision_key=_new_key(),
        event_key=_clean(event_key or assigned, 64),
        proposal_id=None,
        resource_key=resource_key,
        action="release",
        reason=_clean(reason, 255),
        decided_by=_clean(decided_by, 64),
        detail_json=json.dumps(
            {
                "action": "release",
                "released_from": status_before,
                "assigned_event": assigned,
            },
            default=str,
        ),
        resource_status_before=status_before,
        resource_status_after=status_after,
    )
    session.add(row)
    session.flush()
    return {
        "released": True,
        "resource_status_before": status_before,
        "resource_status_after": status_after,
        "status_changed": status_before != status_after,
        "decision": row.as_dict,
    }


def list_active_assignments(session: Session) -> list[dict[str, Any]]:
    """Every busy unit and the incident it is currently booked to (EM-053)."""
    busy = list(
        session.scalars(
            select(SuppressionResource).where(
                SuppressionResource.status.in_(tuple(sorted(_BUSY_STATUSES)))
            )
        )
    )
    assignments: list[dict[str, Any]] = []
    for resource in busy:
        assigned = _active_assignment_event(session, resource)
        if assigned is None:
            continue
        event = session.scalar(select(FireEvent).where(FireEvent.event_key == assigned))
        assignments.append(
            {
                "resource_key": str(resource.resource_key),
                "resource_status": str(resource.status),
                "event_key": assigned,
                "event_status": str(event.status) if event is not None else None,
            }
        )
    return assignments


def release_completed_assignments(session: Session) -> dict[str, Any]:
    """Auto-free every unit whose incident is no longer active (EM-053).

    "Görev bitince kaynak otomatik müsait olur": once a fire event is contained
    /closed (or its row is gone) its booked units return to ``available`` so
    global capacity (EM-028) is computed correctly without a manual release.
    """
    released: list[dict[str, Any]] = []
    for assignment in list_active_assignments(session):
        if assignment["event_status"] == "active":
            continue
        result = release_assignment(
            session,
            resource_key=assignment["resource_key"],
            event_key=assignment["event_key"],
            reason="incident completed - automatic release (EM-053)",
        )
        if result["released"]:
            released.append(
                {
                    "resource_key": assignment["resource_key"],
                    "event_key": assignment["event_key"],
                }
            )
    return {"released": released, "count": len(released)}
