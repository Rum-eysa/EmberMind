"""Unified, immutable audit ledger (EM-096, Epic E10).

Earlier epics recorded accountability *per feature*: capacity-assumption edits
went to ``capacity_assumption_audit`` (EM-034), operator accept/reject decisions
to ``recommendation_decisions`` (EM-047), share-policy edits and webhook
deliveries to their own tables. Each told only its own story - a manager who
asks the EM-096 question "who made which decision, when, and how?" has to join
several unrelated histories by hand, and nothing guarantees the record cannot be
altered after the fact.

This is the single, cross-domain accountability ledger. One append-only row per
governance-relevant action, regardless of which subsystem produced it: a stable
``domain`` (karar / varsayım / senaryo / eşik / paylaşım …), a controlled
``action``, the ``subject_key`` it acted on, the ``actor`` responsible, a
JSON snapshot of the ``old_value`` -> ``new_value`` transition and a human
``summary``. The service exposes only record / list / config - there is
deliberately **no update and no delete** path, so "kayıtlar silinemez" holds at
the application seam (the acceptance criterion for EM-096). The per-feature
tables above are left untouched; this ledger is purely additive and reads never
write.
"""
import json
from typing import Any

from sqlalchemy import Column, Index, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class AuditTrailEntry(BaseModel):
    """An append-only, cross-domain accountability record."""

    __tablename__ = "audit_trail"

    audit_key = Column(String(64), unique=True, nullable=False, index=True)
    domain = Column(String(32), nullable=False, index=True)
    action = Column(String(48), nullable=False, index=True)
    subject_key = Column(String(96), nullable=True, index=True)
    actor = Column(String(64), nullable=False, index=True)
    # A human-readable one-liner of what happened (never a raw stack trace).
    summary = Column(String(255), nullable=False, default="")
    # JSON snapshots of the value transition; a create has no old, a delete of
    # a live row keeps the old and clears the new - both still recorded here.
    old_value_json = Column(Text, nullable=False, default="null")
    new_value_json = Column(Text, nullable=False, default="null")

    __table_args__ = (
        Index("idx_audit_trail_domain_created", "domain", "id"),
        Index("idx_audit_trail_actor", "actor", "id"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return an API-friendly representation with decoded value snapshots."""
        return {
            "id": self.id,
            "audit_key": self.audit_key,
            "domain": self.domain,
            "action": self.action,
            "subject_key": self.subject_key,
            "actor": self.actor,
            "summary": self.summary,
            "old_value": _decode(self.old_value_json),
            "new_value": _decode(self.new_value_json),
            # ``created_at`` is when the action was recorded (the "ne zaman").
            "created_at": to_utc_iso(self.created_at),
        }


def _decode(raw: Any) -> Any:
    """Best-effort decode of a stored JSON value snapshot; never raises."""
    if raw is None:
        return None
    try:
        return json.loads(str(raw))
    except (ValueError, TypeError):
        return None
