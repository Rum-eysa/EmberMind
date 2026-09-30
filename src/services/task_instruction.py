"""Field task instruction cards from accepted proposals (EM-051, Epic E5).

A field team leader wants a *short task card* from an accepted proposal: where
to go (target), when to arrive (ETA) and how dangerous it looks (risk note).
Accepted resources are no longer "available", so they drop out of the live
EM-052 proposal list - the card is therefore reconstructed from the EM-047
decision audit (which snapshots the proposal the operator accepted) joined with
the incident (the target) and the EM-029 risk engine (the risk note). Computed
live on every request; nothing new is persisted.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.recommendation import RecommendationDecision
from src.models.spatial import FireEvent
from src.services.inventory import get_resource
from src.services.risk_index import RiskIndexError, compute_risk_index
from src.utils.timeutils import to_utc_iso

TASK_CARD_ATTRIBUTION = "Kabul edilen öneriden saha ekibi için görev kartı (hedef + varış + risk notu): EM-051"

# Actions that commit a unit to a task and therefore produce a card.
_COMMITTING_ACTIONS = ("accept", "edit")


class TaskInstructionError(RuntimeError):
    """Raised when a task card cannot be produced (unknown fire event)."""


def _risk_note(
    session: Session, settings: Any, event_key: str
) -> dict[str, Any] | None:
    """Peak-band risk summary for one incident, for the card's risk note."""
    try:
        scored = compute_risk_index(session, settings, event_key)["events"]
    except RiskIndexError:
        return None
    if not scored:
        return None
    event = scored[0]
    if event["peak_risk_index"] is None:
        return None  # no measurable demand -> the card carries no risk note
    return {
        "level": event["peak_level"],
        "risk_index": event["peak_risk_index"],
        "horizon_minutes": event["peak_horizon_minutes"],
    }


def _committed_decisions(
    session: Session, event_key: str | None
) -> list[RecommendationDecision]:
    """Newest accept/edit decision per (resource, incident), never-recomputed.

    Only decisions that carry an ``event_key`` become cards - a booking with no
    incident has no target. Reading the audit (not the live proposals) is what
    lets a card survive the unit leaving the "available" pool.
    """
    query = (
        select(RecommendationDecision)
        .where(RecommendationDecision.action.in_(_COMMITTING_ACTIONS))
        .where(RecommendationDecision.event_key.is_not(None))
        .order_by(RecommendationDecision.id.desc())
    )
    if event_key:
        query = query.where(RecommendationDecision.event_key == event_key)
    rows = session.scalars(query).all()
    seen: set[tuple[str, str]] = set()
    unique: list[RecommendationDecision] = []
    for row in rows:
        pair = (str(row.resource_key), str(row.event_key))
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(row)
    return unique


def _build_card(
    session: Session,
    decision: RecommendationDecision,
    risk_note: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Assemble one task card, or ``None`` when its target event is gone."""
    event_key = str(decision.event_key)
    event = session.scalar(select(FireEvent).where(FireEvent.event_key == event_key))
    if event is None:
        return None
    resource = get_resource(session, str(decision.resource_key))
    detail = decision.as_dict["detail"]
    eta = detail.get("eta_minutes")
    if eta is None:
        eta = detail.get("arrival_minutes")
    return {
        "resource_key": str(decision.resource_key),
        "resource_name": str(resource.name) if resource else detail.get("name"),
        "resource_type": (
            str(resource.resource_type) if resource else detail.get("resource_type")
        ),
        "resource_status": str(resource.status) if resource else None,
        "event_key": event_key,
        "target": {
            "event_key": event_key,
            "name": str(event.name),
            "latitude": float(event.latitude),  # type: ignore[arg-type]
            "longitude": float(event.longitude),  # type: ignore[arg-type]
        },
        "travel_mode": detail.get("travel_mode"),
        "eta_minutes": eta,
        "distance_km": detail.get("distance_km"),
        "arrival_eta": (
            to_utc_iso(resource.arrival_eta)
            if resource is not None and resource.arrival_eta
            else None
        ),
        "risk_note": risk_note,
        "accepted_at": to_utc_iso(decision.created_at),
        "decided_by": decision.decided_by,
    }


def generate_task_cards(
    session: Session, settings: Any, event_key: str | None = None
) -> list[dict[str, Any]]:
    """Short field task cards for every committed (accepted/edited) proposal.

    Raises :class:`TaskInstructionError` when an explicit ``event_key`` does not
    reference a known fire event; without an ``event_key`` it returns cards for
    every incident that currently has committed units.
    """
    if event_key:
        exists = session.scalar(
            select(FireEvent).where(FireEvent.event_key == event_key)
        )
        if exists is None:
            raise TaskInstructionError(f"fire event {event_key} not found")

    risk_cache: dict[str, dict[str, Any] | None] = {}
    cards: list[dict[str, Any]] = []
    for decision in _committed_decisions(session, event_key):
        key = str(decision.event_key)
        if key not in risk_cache:
            risk_cache[key] = _risk_note(session, settings, key)
        card = _build_card(session, decision, risk_cache[key])
        if card is not None:
            cards.append(card)
    cards.sort(
        key=lambda c: (
            str(c["event_key"]),
            c["eta_minutes"] if c["eta_minutes"] is not None else float("inf"),
        )
    )
    return cards
