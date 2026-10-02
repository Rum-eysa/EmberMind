"""Single-page situation report (SITREP) for PDF export (EM-087, Epic E8).

A commander has to brief the chain of command and, for a cross-border incident,
the neighbouring country (EM-087 user story: "as a commander I want a one-page
status report as a PDF so I can forward it to higher authority and the other
country"). Every ingredient already exists but is scattered across panels:
active fires (``fire_events``), the spread forecast and per-horizon risk
(EM-029 ``compute_risk_index``), ranked dispatch recommendations (EM-052
``build_proposals``) and the synthetic-data label the demo generator stamps on
seeded incidents (EM-104). No single surface assembles them into one printable
page, and nothing carries a report timestamp.

This service is a **read-time projection** (``persistence`` is ``none`` - no new
table, no migration). ``build_sitrep`` gathers, in one deterministic pass:

* **fires** - every active incident with its core fields (name, position,
  severity, status, when it started);
* **forecast** - the EM-029 per-horizon spread projection (predicted area in ha)
  that the risk trajectory is derived from;
* **risk_index** - the per-event peak band plus the whole-report summary
  (band counts and the single hottest incident);
* **recommendations** - the top-ranked dispatch proposals for the hottest
  incident, degrading gracefully (``available`` false with a reason) when no
  road network / resource is present so a report is still produced;
* **timestamp** - the ``generated_at`` wall-clock the page is stamped with;
* **synthetic badge** - a prominent flag when any reported incident is demo /
  synthetic data (acceptance: "the synthetic-data badge must show on the report
  too").

The PDF itself is an operator-side print of the rendered page (the map tiles a
print-friendly report would embed are a client concern); the backend contract
is the fully assembled, ordered, single-page structure. Two runs over the same
data always yield the same report.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import FireEvent
from src.services.positioning import PositioningError, build_proposals
from src.services.risk_index import RISK_LEVELS, RiskIndexError, compute_risk_index
from src.services.road_network import RoadNetworkError
from src.services.synthetic import SYNTHETIC_LABEL
from src.utils.timeutils import to_utc_iso, utc_now

# Severity ranking (EM-031 vocabulary) for the report ordering and headline.
_SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
SEVERITY_ORDER = ("critical", "high", "medium", "low")

# Ordered sections the one-page report always carries (acceptance surface list).
REPORT_SECTIONS = (
    "fires",
    "forecast",
    "risk_index",
    "recommendations",
    "timestamp",
)

# Marker (lower-cased) that flags a seeded demo incident; the generator stamps
# ``SYNTHETIC_LABEL`` onto the incident's free-text notes (EM-104).
_SYNTHETIC_MARKER = "sentetik"

MAX_FIRES = 20
RECOMMENDATION_LIMIT = 5

SITREP_ATTRIBUTION = (
    "EM-087: tek sayfalık durum raporu (SITREP) aktif yangın, yayılım tahmini, "
    "risk indeksi ve konuşlanma önerilerini okuma zamanı tek sayfada derler; "
    "sentetik veri rozeti ve zaman damgası taşır, PDF/Yazdır ile dışa aktarılır"
)
SITREP_PERSISTENCE = "none"
SITREP_EXPORT_FORMATS = ("pdf", "print")


def _rank(severity: Any) -> int:
    """Map a severity string to its urgency rank (unknown -> lowest)."""
    return _SEVERITY_RANK.get(str(severity).strip().lower(), 0)


def _max_fires(settings: Any) -> int:
    """Positive fire-list cap from settings, falling back to ``MAX_FIRES``."""
    try:
        want = int(getattr(settings, "SITREP_MAX_FIRES", MAX_FIRES))
    except (TypeError, ValueError):
        return MAX_FIRES
    return max(1, want)


def _rec_limit(settings: Any) -> int:
    """Positive recommendation-list cap, falling back to the default."""
    try:
        want = int(
            getattr(settings, "SITREP_RECOMMENDATION_LIMIT", RECOMMENDATION_LIMIT)
        )
    except (TypeError, ValueError):
        return RECOMMENDATION_LIMIT
    return max(0, want)


def _meta_map(session: Session, event_keys: list[str]) -> dict[str, FireEvent]:
    """event_key -> FireEvent row so the risk projection can be enriched with
    severity, start time and the synthetic-data note the generator stamps."""
    if not event_keys:
        return {}
    rows = session.scalars(
        select(FireEvent).where(FireEvent.event_key.in_(event_keys))
    ).all()
    return {str(row.event_key): row for row in rows}


def _started_iso(event: Optional[FireEvent]) -> Optional[str]:
    """ISO-8601 UTC start time, ``None`` when the row is absent or malformed."""
    if event is None:
        return None
    started = event.started_at
    if isinstance(started, datetime):
        return to_utc_iso(started)
    return None


def _synthetic_state(events: list[Optional[FireEvent]]) -> dict[str, Any]:
    """Whether any reported incident is synthetic demo data + the badge label.

    The EM-104 generator stamps ``SYNTHETIC_LABEL`` into a seeded incident's
    notes; presence of the marker on any reported fire raises the report-wide
    badge so a forwarded PDF can never be mistaken for a live observation.
    """
    matched: list[str] = []
    for event in events:
        if event is None:
            continue
        notes = str(event.notes or "")
        if (
            _SYNTHETIC_MARKER in notes.lower()
            or SYNTHETIC_LABEL.lower() in notes.lower()
        ):
            matched.append(str(event.event_key))
    return {
        "is_synthetic": bool(matched),
        "badge": SYNTHETIC_LABEL if matched else None,
        "label": SYNTHETIC_LABEL,
        "matched_events": sorted(matched),
    }


def _recommendations(
    session: Session, settings: Any, event_key: Optional[str], limit: int
) -> dict[str, Any]:
    """Top dispatch proposals for one incident, or a graceful unavailable note.

    An incident with no road network or no available resource still yields a
    complete report: the section is flagged ``available`` false with the reason
    instead of raising, so the page is printable in every deployment state.
    """
    if not event_key:
        return {
            "available": False,
            "for_event": None,
            "reason": "bildirime konu aktif yangın yok",
            "items": [],
        }
    try:
        proposals = build_proposals(session, settings, event_key, limit=limit)
    except (RoadNetworkError, PositioningError, RiskIndexError) as exc:
        return {
            "available": False,
            "for_event": event_key,
            "reason": str(exc),
            "items": [],
        }
    items = [
        {
            "rank": index + 1,
            "resource_key": proposal.get("resource_key"),
            "name": proposal.get("name"),
            "resource_type": proposal.get("resource_type"),
            "travel_mode": proposal.get("travel_mode"),
            "reachable": bool(proposal.get("reachable")),
            "eta_minutes": proposal.get("eta_minutes"),
        }
        for index, proposal in enumerate(proposals)
    ]
    return {
        "available": True,
        "for_event": event_key,
        "reason": None,
        "items": items,
    }


def _report_order(risk_events: list[dict[str, Any]], meta: dict[str, FireEvent]):
    """Order reported fires: most severe first, then hottest risk, then key.

    ``peak_risk_index`` of ``None`` (no capacity / no forecast) sorts lowest so a
    measured hot incident always leads. Deterministic on equal keys.
    """
    decorated = []
    for event in risk_events:
        key = str(event["event_key"])
        row = meta.get(key)
        severity = str(row.severity) if row is not None else "low"
        peak = event.get("peak_risk_index")
        peak_value = float(peak) if peak is not None else -1.0
        decorated.append(((-_rank(severity), -peak_value, key), key, event, row))
    decorated.sort(key=lambda item: item[0])
    return [(key, event, row) for _, key, event, row in decorated]


def build_sitrep(
    session: Session, settings: Any, *, event_key: Optional[str] = None
) -> dict[str, Any]:
    """Assemble the one-page situation report as a read-time projection.

    Scores the incidents through EM-029 (an explicit ``event_key`` scopes the
    report to one incident; otherwise every active fire is included), enriches
    each with severity / start time / synthetic state from ``fire_events`` and
    attaches the top recommendations for the hottest incident. An unknown
    ``event_key`` propagates :class:`RiskIndexError` (the route maps it to 404).
    """
    risk = compute_risk_index(session, settings, event_key)
    limit = _max_fires(settings)
    rec_limit = _rec_limit(settings)

    risk_events = list(risk.get("events", []))
    all_keys = [str(e["event_key"]) for e in risk_events]
    meta = _meta_map(session, all_keys)

    ordered = _report_order(risk_events, meta)
    reported = ordered[:limit]

    fires: list[dict[str, Any]] = []
    forecast_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    for key, event, row in reported:
        severity = str(row.severity) if row is not None else "low"
        horizons = list(event.get("horizons", []))
        fires.append(
            {
                "event_key": key,
                "name": str(row.name) if row is not None else key,
                "severity": severity,
                "severity_rank": _rank(severity),
                "status": str(event.get("status", "active")),
                "started_at": _started_iso(row),
                "latitude": round(float(event["latitude"]), 4),
                "longitude": round(float(event["longitude"]), 4),
                "peak_level": event.get("peak_level"),
                "peak_risk_index": event.get("peak_risk_index"),
            }
        )
        forecast_rows.append(
            {
                "event_key": key,
                "horizons": [
                    {
                        "horizon_minutes": h["horizon_minutes"],
                        "area_ha": h["area_ha"],
                        "level": h["level"],
                    }
                    for h in horizons
                ],
            }
        )
        risk_rows.append(
            {
                "event_key": key,
                "peak_level": event.get("peak_level"),
                "peak_risk_index": event.get("peak_risk_index"),
                "peak_horizon_minutes": event.get("peak_horizon_minutes"),
            }
        )

    summary = risk.get("summary", {})
    rec_target = event_key or (summary.get("max_risk_event") if summary else None)
    if not rec_target and reported:
        rec_target = reported[0][0]

    most_severe: Optional[str] = None
    for key, _event, row in reported:
        severity = str(row.severity) if row is not None else "low"
        if most_severe is None or _rank(severity) > _rank(most_severe):
            most_severe = severity.strip().lower()

    synthetic = _synthetic_state([row for _, _e, row in reported])

    return {
        "panel": "sitrep",
        "title": "Durum Raporu (SITREP)",
        "generated_at": to_utc_iso(utc_now()),
        "scope": {"event_key": event_key},
        "sections": list(REPORT_SECTIONS),
        "fires": fires,
        "fire_count": len(fires),
        "active_fire_total": len(risk_events),
        "forecast": {
            "horizon_minutes": list(risk.get("horizon_minutes", [])),
            "per_event": forecast_rows,
        },
        "risk_index": {
            "levels": list(risk.get("levels", RISK_LEVELS)),
            "unit": risk.get("unit"),
            "thresholds": risk.get("thresholds"),
            "capacity_effective_ha_h": risk.get("capacity_effective_ha_h"),
            "per_event": risk_rows,
            "summary": summary,
        },
        "recommendations": _recommendations(session, settings, rec_target, rec_limit),
        "synthetic": synthetic,
        "headline": {
            "reported_fire_count": len(fires),
            "active_fire_total": len(risk_events),
            "most_severe": most_severe,
            "max_risk_level": summary.get("max_risk_level"),
            "status": "aktif yangın var" if risk_events else "aktif yangın yok",
        },
        "max_fires": limit,
        "recommendation_limit": rec_limit,
        "export": {"formats": list(SITREP_EXPORT_FORMATS), "one_click": True},
        "attribution": SITREP_ATTRIBUTION,
        "persistence": SITREP_PERSISTENCE,
    }


def sitrep_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: report sections, vocabularies and export options."""
    return {
        "panel": "sitrep",
        "title": "Durum Raporu (SITREP)",
        "sections": list(REPORT_SECTIONS),
        "export": {"formats": list(SITREP_EXPORT_FORMATS), "one_click": True},
        "synthetic_badge_label": SYNTHETIC_LABEL,
        "risk_levels": list(RISK_LEVELS),
        "severities": list(SEVERITY_ORDER),
        "max_fires": _max_fires(settings) if settings is not None else MAX_FIRES,
        "recommendation_limit": (
            _rec_limit(settings) if settings is not None else RECOMMENDATION_LIMIT
        ),
        "sources": [
            "fire_events (active, EM-005)",
            "risk_index (EM-029 tahmin + risk)",
            "positioning proposals (EM-052 öneriler)",
            "synthetic label (EM-104)",
        ],
        "attribution": SITREP_ATTRIBUTION,
        "persistence": SITREP_PERSISTENCE,
    }


__all__ = [
    "MAX_FIRES",
    "RECOMMENDATION_LIMIT",
    "REPORT_SECTIONS",
    "SEVERITY_ORDER",
    "SITREP_ATTRIBUTION",
    "SITREP_EXPORT_FORMATS",
    "SITREP_PERSISTENCE",
    "build_sitrep",
    "sitrep_config",
]
