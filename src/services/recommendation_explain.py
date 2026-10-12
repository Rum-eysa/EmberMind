"""Explainable positioning recommendations (EM-046, Epic E5).

The commander needs to know *why* the engine (EM-052) proposes a resource before
deciding to trust it. This service adds a "why?" narrative to every ranked
proposal and — critically — surfaces the **alternatives that were evaluated but
not recommended**, each with the reason it lost. Nothing here re-ranks: it reuses
:func:`build_proposals` and annotates its output, so the explanation can never
drift from the numbers the map already shows.

Criterion mapping:
* "hangi tahmin"  -> the closure-aware route ETA (the metric that ranks proposals).
* "hangi eşik"    -> the top-N selection cut (``POSITIONING_MAX_PROPOSALS``) plus
  the active-closure context that shaped the ETAs.
* "hangi alternatifler değerlendirildi" -> every available origin considered,
  split into recommended and rejected (with per-item reasons).
"""
from __future__ import annotations

from typing import Any

from src.services.positioning import build_proposals

EXPLAIN_ATTRIBUTION = "Öneri gerekçesi + reddedilen alternatifler (EM-046)"

# A very large internal cap: fetch the *full* ranking, then split it ourselves so
# the rejected alternatives are exactly the proposals the top-N cut dropped.
_ALL_LIMIT = 1_000_000


def _fmt_eta(proposal: dict[str, Any]) -> str:
    eta = proposal.get("eta_minutes")
    return f"T+{eta} dk" if eta is not None else "varış hesaplanamadı"


def _why_selected(proposal: dict[str, Any], rank: int) -> list[str]:
    """Human-readable reasons a proposal made the recommended set."""
    reasons: list[str] = []
    if not proposal["reachable"]:
        reasons.append(
            "Karayoluyla şu an ulaşılamıyor; yine de en iyi adaylar arasında "
            "listeleniyor."
        )
    else:
        head = "En kısa tahmini varış" if rank == 1 else "ETA sıralamasında önde"
        km = proposal.get("distance_km")
        dist = f" ({km} km)" if km is not None else ""
        reasons.append(f"{head}: {_fmt_eta(proposal)}{dist}.")
    delay = proposal.get("delay_vs_open_minutes") or 0.0
    if delay > 0:
        reasons.append(f"Aktif yol kapanışları açık ağa göre +{delay} dk ekliyor.")
    else:
        reasons.append("Aktif yol kapanışlarından ek gecikme görmüyor.")
    return reasons


def _why_rejected(proposal: dict[str, Any], threshold_eta: float | None) -> str:
    """The single reason an evaluated alternative lost the top-N cut."""
    if not proposal["reachable"]:
        return "Olaya aktif yol ağıyla ulaşılamıyor (izole/kopuk kaynak)."
    eta = proposal.get("eta_minutes")
    if eta is not None and threshold_eta is not None and eta >= threshold_eta:
        return (
            f"Daha uzun tahmini varış: {_fmt_eta(proposal)} "
            f"(önerilen eşik T+{round(threshold_eta, 2)} dk)."
        )
    return "Sıralamada önerilenlerin altında kaldı."


def explain_proposals(
    session: Any,
    settings: Any,
    event_key: str | None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Full explanation for one event's positioning ranking.

    Returns the recommended proposals (each with a ``why`` list), the rejected
    alternatives (each with a ``reason``), and the shared decision ``context``
    (ranking metric, evaluated counts, top-N threshold and closure impact).
    Raises :class:`PositioningError` / :class:`RoadNetworkError` through
    :func:`build_proposals` for an unknown event or an empty network.
    """
    ranked = build_proposals(session, settings, event_key, limit=_ALL_LIMIT)
    cap = (
        limit
        if limit is not None
        else int(getattr(settings, "POSITIONING_MAX_PROPOSALS", 5))
    )
    cap = max(0, cap)
    selected = ranked[:cap]
    rejected = ranked[cap:]

    reachable_etas = [
        p["eta_minutes"]
        for p in selected
        if p["reachable"] and p["eta_minutes"] is not None
    ]
    threshold_eta = max(reachable_etas) if reachable_etas else None

    proposals: list[dict[str, Any]] = []
    for rank, proposal in enumerate(selected, start=1):
        enriched = dict(proposal)
        enriched["rank"] = rank
        enriched["why"] = _why_selected(proposal, rank)
        proposals.append(enriched)

    alternatives: list[dict[str, Any]] = []
    for proposal in rejected:
        alternatives.append(
            {
                "proposal_id": proposal["proposal_id"],
                "resource_key": proposal["resource_key"],
                "name": proposal["name"],
                "resource_type": proposal["resource_type"],
                "reachable": proposal["reachable"],
                "eta_minutes": proposal["eta_minutes"],
                "distance_km": proposal["distance_km"],
                "reason": _why_rejected(proposal, threshold_eta),
            }
        )

    closure_impacted = sum(
        1 for p in ranked if (p.get("delay_vs_open_minutes") or 0.0) > 0
    )
    context = {
        "event_key": event_key,
        "ranking_metric": "closure-aware road route ETA (dakika)",
        "alternatives_evaluated": len(ranked),
        "selected_limit": cap,
        "threshold_eta_minutes": round(threshold_eta, 2)
        if threshold_eta is not None
        else None,
        "closure_impacted_count": closure_impacted,
    }
    return {
        "count": len(proposals),
        "rejected_count": len(alternatives),
        "event_key": event_key,
        "context": context,
        "proposals": proposals,
        "rejected_alternatives": alternatives,
        "attribution": EXPLAIN_ATTRIBUTION,
    }
