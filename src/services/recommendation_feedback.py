"""Recommendation accept/reject feedback analytics (EM-054, Epic E5).

The data scientist wants to learn *which* suggestions operators reject and
*why*, so the recommendation engine can be tuned. EM-047 already persists every
accept / reject / edit decision (with an optional reason and a snapshot of the
proposal it acted on) as an immutable audit trail; this module turns that trail
into an aggregate report - no new tables, nothing written, read-only analytics
over the EM-047 audit.

It answers the EM-054 acceptance criteria directly:
- accept/reject **rates** overall and per resource type (with the recorded
  reasons);
- the **most-rejected** resource types;
- **improvement ideas** distilled from the above, ready to hand to the backlog.

Only the three proposal-decision actions (``accept``/``reject``/``edit``) are
counted; the EM-053 ``release`` lifecycle rows are not operator judgements on a
proposal and are excluded.
"""
from collections import Counter
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.inventory import SuppressionResource
from src.models.recommendation import DECISION_ACTIONS, RecommendationDecision
from src.utils.timeutils import to_utc_iso, utc_now

FEEDBACK_PANEL = "recommendation_feedback"
FEEDBACK_ATTRIBUTION = (
    "Öneri kabul/ret geri bildirim döngüsü: EM-047 denetim kaydının "
    "toplu analizi (oranlar, en çok reddilen tipler, gerekçeler, iyileştirme "
    "fikirleri) (EM-054)"
)
FEEDBACK_PERSISTENCE = "none"
FEEDBACK_SOURCE = "recommendation_decisions (EM-047)"
# Row window for the scan; newest rows win, matching the audit listing order.
_FEEDBACK_ROW_LIMIT = 2000
_TOP_N = 5
# A type is called out for tuning when at least this share of its proposals was
# rejected (and it was actually proposed/rejected at least once).
_REJECT_RATE_ALERT = 0.5
# A low overall acceptance share is itself a signal that the engine is off.
_ACCEPT_RATE_WARN = 0.5
_MIN_DECISIONS_FOR_WARN = 3
_UNKNOWN_TYPE = "bilinmeyen"

# Keyword -> backlog idea, matched against reject reasons to make the feedback
# loop actionable rather than just descriptive.
_REASON_IDEAS: tuple[tuple[str, str], ...] = (
    (
        "yavaş",
        "Varış süresi (ETA) tahminlerini iyileştir; yavaş bulunan öneriler daha düşük öncelik almalı.",
    ),
    (
        "uzak",
        "Mesafe/menzil ağırlığını artır; çok uzak kaynaklar öneri listenin başında çıkmasın.",
    ),
    (
        "geç",
        "ETA/uygulanabilirlik zamanlamasını sıkılaştır; geç kalınan öneriler elensin.",
    ),
    (
        "menzil",
        "Menzil limitini öneri sıralamasına fiyatla (EM-050 kısıtı ile tutarlı).",
    ),
    ("yakıt", "Yakıt/dayanıklılık kontrolünü öneri üretimine fiyatla."),
    ("mesai", "Mesai/vardiya limitini öneri üretimine fiyatla."),
    ("gece", "Gece yetkisi kısıtını öneri üretimine fiyatla (EM-050)."),
    ("çakış", "Kaynak çakışma/müsaitlik durumunu sıralamaya yansıt (EM-053)."),
    ("cakisma", "Kaynak çakışma/müsaitlik durumunu sıralamaya yansıt (EM-053)."),
)


def _resource_type_lookup(session: Session) -> dict[str, str]:
    """Best-effort ``resource_key -> resource_type`` map for the inventory."""
    rows = session.execute(
        select(SuppressionResource.resource_key, SuppressionResource.resource_type)
    ).all()
    return {str(key): str(rtype).strip().lower() for key, rtype in rows}


def _clean_type(row: dict[str, Any], table_map: dict[str, str]) -> str:
    """Resolve the proposal's resource type from the snapshot, else inventory."""
    detail = row.get("detail") or {}
    rtype = detail.get("resource_type")
    if rtype:
        return str(rtype).strip().lower()
    return table_map.get(str(row.get("resource_key")), _UNKNOWN_TYPE)


def _rate(count: int, total: int) -> Optional[float]:
    """Share of ``count`` in ``total``; ``None`` when there is nothing to divide."""
    if total <= 0:
        return None
    return round(count / total, 3)


def _reason_ideas(reason_counts: Counter) -> list[str]:
    """Map the most common reject reasons onto concrete backlog ideas."""
    ideas: list[str] = []
    seen: set[str] = set()
    for reason, _count in reason_counts.most_common(_TOP_N):
        lowered = reason.lower()
        for needle, idea in _REASON_IDEAS:
            if needle in lowered and idea not in seen:
                seen.add(idea)
                ideas.append(idea)
    return ideas


def _improvement_ideas(
    per_type: list[dict[str, Any]],
    reason_counts: Counter,
    totals: dict[str, int],
) -> list[str]:
    """Distil the aggregates into prioritised, hand-to-backlog suggestions."""
    ideas: list[str] = []
    decisions = totals["decisions"]
    if decisions == 0:
        return [
            "Henüz kayıtlı operatör kararı yok; kararlar biriktikçe bu geri "
            "bildirim döngüsü motoru iyileştirecek somut fikirler üretir."
        ]
    if (
        decisions >= _MIN_DECISIONS_FOR_WARN
        and (totals["accept"] / decisions) < _ACCEPT_RATE_WARN
    ):
        ideas.append(
            f"Genel kabul oranı %{round(100 * totals['accept'] / decisions)} — "
            "öneri motoru operatör beklentisini karşılamıyor; gerekçe kümesine "
            "göre girdi/ağırlık revizyonu önerilir."
        )
    for row in per_type:
        reject_rate = row["reject_rate"]
        if (
            reject_rate is not None
            and reject_rate >= _REJECT_RATE_ALERT
            and row["reject"] >= 1
        ):
            ideas.append(
                f"'{row['resource_type']}' tipi öneriler %{round(100 * reject_rate)} "
                "oranında reddediliyor — bu tipin uygunluk/önceliklendirmesini "
                "gözden geçir."
            )
    ideas.extend(_reason_ideas(reason_counts))
    # De-duplicate while preserving the priority order established above.
    unique: list[str] = []
    for idea in ideas:
        if idea not in unique:
            unique.append(idea)
    return unique


def feedback_summary(
    session: Session, event_key: Optional[str] = None
) -> dict[str, Any]:
    """Aggregate the EM-047 decision audit into an accept/reject feedback report.

    ``event_key`` narrows the analysis to one incident; ``None`` analyses every
    recorded operator decision. Resource types are resolved from the decision
    snapshot when present, otherwise from the current inventory, so the report
    stays meaningful even for decisions recorded without a full snapshot.
    """
    query = (
        select(RecommendationDecision)
        .where(RecommendationDecision.action.in_(DECISION_ACTIONS))
        .order_by(RecommendationDecision.id.desc())
        .limit(_FEEDBACK_ROW_LIMIT)
    )
    if event_key:
        query = query.where(RecommendationDecision.event_key == event_key)
    rows = [row.as_dict for row in session.scalars(query).all()]
    table_map = _resource_type_lookup(session)

    action_counts: Counter = Counter()
    type_counts: dict[str, Counter] = {}
    reason_counts: Counter = Counter()
    for row in rows:
        action = str(row["action"])
        action_counts[action] += 1
        rtype = _clean_type(row, table_map)
        bucket = type_counts.setdefault(rtype, Counter())
        bucket[action] += 1
        if action == "reject":
            reason = (row.get("reason") or "").strip()
            reason_counts[reason or "gerekçe belirtilmemiş"] += 1

    decisions = sum(action_counts[action] for action in DECISION_ACTIONS)
    totals = {action: int(action_counts[action]) for action in DECISION_ACTIONS}
    totals["decisions"] = decisions
    rates = {
        "accept_rate": _rate(totals["accept"], decisions),
        "reject_rate": _rate(totals["reject"], decisions),
        "edit_rate": _rate(totals["edit"], decisions),
    }

    per_type: list[dict[str, Any]] = []
    for rtype, bucket in type_counts.items():
        type_total = sum(bucket[action] for action in DECISION_ACTIONS)
        per_type.append(
            {
                "resource_type": rtype,
                "decisions": type_total,
                "accept": int(bucket["accept"]),
                "reject": int(bucket["reject"]),
                "edit": int(bucket["edit"]),
                "accept_rate": _rate(bucket["accept"], type_total),
                "reject_rate": _rate(bucket["reject"], type_total),
            }
        )
    per_type.sort(key=lambda row: (-row["decisions"], row["resource_type"]))

    most_rejected = sorted(
        (row for row in per_type if row["reject"] > 0),
        key=lambda row: (-row["reject"], -(row["reject_rate"] or 0.0)),
    )[:_TOP_N]

    return {
        "panel": FEEDBACK_PANEL,
        "scope": event_key or "all",
        "event_key": event_key,
        "generated_at": to_utc_iso(utc_now()),
        "actions": list(DECISION_ACTIONS),
        "totals": totals,
        "rates": rates,
        "by_resource_type": per_type,
        "most_rejected_types": most_rejected,
        "rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in reason_counts.most_common(_TOP_N)
        ],
        "improvement_ideas": _improvement_ideas(per_type, reason_counts, totals),
        "top_n": _TOP_N,
        "reject_rate_alert": _REJECT_RATE_ALERT,
        "source": FEEDBACK_SOURCE,
        "attribution": FEEDBACK_ATTRIBUTION,
        "persistence": FEEDBACK_PERSISTENCE,
    }


__all__ = [
    "FEEDBACK_ATTRIBUTION",
    "FEEDBACK_PANEL",
    "FEEDBACK_PERSISTENCE",
    "FEEDBACK_SOURCE",
    "feedback_summary",
]
