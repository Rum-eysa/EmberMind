"""Operator decisions on positioning proposals (EM-047, Epic E5).

EM-052 ranks available resources and proposes deployment for a fire event, but
the *final call always belongs to the operator*. EM-047 persists that call: an
accept / reject / edit decision on a proposal. Accepting (or editing then
accepting) commits the proposed resource by moving it to the ``en_route``
("yolda") status (EM-031 vocabulary); rejecting records an optional reason and
leaves the resource untouched. Every decision is written as an immutable audit
row so the chain of "who decided what, and why" can be reconstructed later.

The proposal itself is not stored (it is recomputed live by EM-052); a decision
only snapshots the inputs it acted on (``proposal_id``, ETA, deployment point)
so the audit stays self-describing even after the underlying ranking changes.
"""
import json
from typing import Any

from sqlalchemy import Column, Index, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# The three operator actions (EM-047: "Üç aksiyon vardır").
DECISION_ACTIONS = ("accept", "reject", "edit")


class RecommendationDecision(BaseModel):
    """An immutable audit row for one operator decision on a proposal."""

    __tablename__ = "recommendation_decisions"

    decision_key = Column(String(64), unique=True, nullable=False, index=True)
    event_key = Column(String(64), nullable=True, index=True)
    proposal_id = Column(String(96), nullable=True)
    resource_key = Column(String(64), nullable=False, index=True)
    action = Column(String(16), nullable=False, index=True)
    # Optional human note; mandatory only conceptually for a reject, so the
    # service records whatever is supplied without forcing it (acceptance:
    # "Reddin gerekçesi zorunlu değil ama isteğe bağlı kaydedilir").
    reason = Column(String(255), nullable=True)
    decided_by = Column(String(64), nullable=True)
    # Snapshot of the proposal the decision acted on plus the operator's edits.
    detail_json = Column(Text, nullable=False, default="{}")
    resource_status_before = Column(String(32), nullable=True)
    resource_status_after = Column(String(32), nullable=True)

    __table_args__ = (
        Index("idx_rec_decisions_event_created", "event_key", "id"),
        Index("idx_rec_decisions_resource", "resource_key", "id"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return an API-friendly representation with the decoded detail."""
        return {
            "id": self.id,
            "decision_key": self.decision_key,
            "event_key": self.event_key,
            "proposal_id": self.proposal_id,
            "resource_key": self.resource_key,
            "action": self.action,
            "reason": self.reason,
            "decided_by": self.decided_by,
            "detail": _decode_detail(self.detail_json),
            "resource_status_before": self.resource_status_before,
            "resource_status_after": self.resource_status_after,
            "created_at": to_utc_iso(self.created_at),
        }


def _decode_detail(raw: Any) -> dict[str, Any]:
    """Best-effort decode of the stored ``detail_json`` into a dict."""
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
