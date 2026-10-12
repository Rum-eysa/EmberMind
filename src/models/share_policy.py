"""Country / role data-sharing policy (EM-070, Epic E7).

EM-066 let a coordinator *narrow* what the shared TR/GR screen shows for a
single request; EM-070 is the durable **authorization policy** an administrator
sets so sovereignty and privacy limits hold by default, not per call. A policy
is keyed by the *owner* country (whose data is exposed) and a role scope, and
lists which field groups (``fire`` / ``risk`` / ``support``) may cross to the
partner side.

The table is **append-only**: writing a new policy never overwrites history -
each change inserts a row carrying the previous value, so the newest row for a
(country, role) is the effective policy *and* the whole change series is the
audit trail (EM-047's immutable-row pattern). This satisfies "policy changes are
written to an audit record" with a single additive table.
"""
from typing import Any

from sqlalchemy import Column, Index, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class CountrySharePolicy(BaseModel):
    """One (append-only) data-sharing policy change for a country and role."""

    __tablename__ = "country_share_policy"

    policy_key = Column(String(64), unique=True, nullable=False, index=True)
    # Owner country whose data is shared to the partner (``TR`` / ``GR``).
    viewer_country = Column(String(2), nullable=False, index=True)
    # Role scope the policy applies to; ``*`` is the per-country default.
    role = Column(String(48), nullable=False, index=True, default="*")
    # Canonical, ordered comma list of shared field groups.
    shared_fields = Column(String(64), nullable=False)
    # The value this change replaced, for the audit series (None on first set).
    previous_shared_fields = Column(String(64), nullable=True)
    changed_by = Column(String(64), nullable=True)
    reason = Column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_share_policy_country_role", "viewer_country", "role", "id"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """API-friendly view with the shared fields split into a list."""
        return {
            "id": self.id,
            "policy_key": self.policy_key,
            "viewer_country": self.viewer_country,
            "role": self.role,
            "shared_fields": [
                token for token in str(self.shared_fields).split(",") if token
            ],
            "previous_shared_fields": (
                None
                if self.previous_shared_fields is None
                else [
                    token
                    for token in str(self.previous_shared_fields).split(",")
                    if token
                ]
            ),
            "changed_by": self.changed_by,
            "reason": self.reason,
            "created_at": to_utc_iso(self.created_at),
        }
