"""Operator verification workflow for silent-region alerts (EM-041, Epic E4).

EM-040 pings the operator when a *risky* region goes silent. The operator then
does the thing no derived score can do: confirm whether the alert was real.
EM-041 persists that judgement - one of **verified** ("doğrulandı"),
**false alarm** ("yanlış alarm") or **under review** ("inceleniyor") - so the
detector can be tuned against real outcomes over time (EM-041 acceptance:
"operatör bir sessiz bölgeyi doğrulandı / yanlış alarm / inceleniyor olarak
işaretebilir; bu geri bildirim modelin iyileştirilmesi için kaydedilir").

Unlike the read-time E4 panels, this one **writes**: each marking is an
append-only audit row (the previous verdict is never overwritten), so the full
"who judged what, and why" chain is reconstructable. The *current* verdict for a
region is simply its newest row. ``persistence`` is therefore
``silent_zone_verifications``.
"""
import json
from typing import Any

from sqlalchemy import Column, Index, Integer, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# The three operator verdicts (EM-041: "üç durum vardır").
VERIFICATION_STATUSES = ("verified", "false_alarm", "under_review")
VERIFICATION_LABELS = {
    "verified": "Doğrulandı",
    "false_alarm": "Yanlış alarm",
    "under_review": "İnceleniyor",
}


class SilentZoneVerification(BaseModel):
    """One immutable operator verdict on a silent-region alert."""

    __tablename__ = "silent_zone_verifications"

    verification_key = Column(String(64), unique=True, nullable=False, index=True)
    region_id = Column(Integer, nullable=False, index=True)
    # Snapshot the region name so the audit stays self-describing even if the
    # silent region is later renamed or deactivated.
    region_name = Column(String(128), nullable=True)
    status = Column(String(16), nullable=False, index=True)
    reason = Column(String(255), nullable=True)
    verified_by = Column(String(64), nullable=True)
    # Snapshot of the alert the verdict acted on (risk level, priority, ...).
    detail_json = Column(Text, nullable=False, default="{}")

    __table_args__ = (
        Index("idx_silent_verif_region_created", "region_id", "id"),
        Index("idx_silent_verif_status", "status", "id"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return an API-friendly representation with the decoded detail."""
        return {
            "id": self.id,
            "verification_key": self.verification_key,
            "region_id": self.region_id,
            "region_name": self.region_name,
            "status": self.status,
            "status_label": VERIFICATION_LABELS.get(str(self.status), str(self.status)),
            "reason": self.reason,
            "verified_by": self.verified_by,
            "detail": _decode_detail(self.detail_json),
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
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
