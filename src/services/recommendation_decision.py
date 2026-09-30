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

from src.models.recommendation import DECISION_ACTIONS, RecommendationDecision
from src.services.inventory import get_resource, update_resource

# Committing status applied by an accept / edit (EM-031 "yolda").
_COMMIT_STATUS = "en_route"


class DecisionError(RuntimeError):
    """Raised for an invalid decision (unknown action, missing resource)."""


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
