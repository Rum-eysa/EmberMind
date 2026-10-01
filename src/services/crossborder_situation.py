"""Cross-border shared situation view (EM-066, Epic E7).

The Turkey-Greece coordinator asks for *one* screen that shows both nations'
live situation side by side - which fires are burning in each country, how hard
each is (the EM-029 risk band) and roughly how much international reinforcement
it will need (the EM-065 external-support forecast) - so coordination starts
before a border incident overwhelms one side.

Two things make this safe to share across a border:

* **Country attribution.** ``FireEvent`` stores only a coordinate, so each
  incident is assigned to ``TR`` or ``GR`` from a configurable border longitude
  (east of it is Türkiye, west is Greece). This is a deliberate *pilot
  simplification* of the real Aegean land/sea boundary - the same TR-east /
  GR-west framing EM-063 uses for time zones - exposed so an operator can nudge
  the split to match the corridor they are watching.
* **Data-sharing scope.** Not every field is shareable by default: the caller
  chooses a subset of the ``fire`` / ``risk`` / ``support`` field groups and
  only those are emitted, per country. This is the EM-066 knob for "what may
  both sides see"; the full per-country *authorization* policy is EM-070's
  responsibility, deliberately kept out of scope here.

The whole payload is derived live from the EM-029 risk index and EM-065
external-support forecast; nothing is stored, so ``persistence`` is ``none``.
"""
from typing import Any, Optional, Sequence

from sqlalchemy.orm import Session

from src.services.external_support import forecast_external_support
from src.services.risk_index import RISK_LEVELS, compute_risk_index

# The three shareable field groups. A country row only carries the sections the
# active sharing scope enables, so sensitive blocks can be withheld per view.
SHAREABLE_FIELD_GROUPS = ("fire", "risk", "support")
# Default scope shares everything (EM-066 acceptance: one complete screen); an
# operator narrows it via settings or the ``fields`` request parameter.
DEFAULT_SHARED_FIELDS = "fire,risk,support"

COUNTRIES = ("GR", "TR")
COUNTRY_LABELS = {"TR": "Türkiye", "GR": "Yunanistan"}
# The corridor's east/west split as a single pilot longitude (deg East).
_DEFAULT_BORDER_LONGITUDE = 26.5

CROSSBORDER_ATTRIBUTION = (
    "Sınır ötesi durum: EM-029 risk indeksi / EM-065 dış destek tahmini; "
    "ülke atfı yapılandırılabilir sınır boylamı ile (pilot basitleştirmesi)."
)


class CrossborderError(ValueError):
    """Raised for an invalid data-sharing field selection."""


def border_longitude(settings: Any) -> float:
    """The configured pilot border longitude (shared by EM-066/EM-067)."""
    return float(
        getattr(settings, "CROSSBORDER_BORDER_LONGITUDE", _DEFAULT_BORDER_LONGITUDE)
    )


def country_for(longitude: float, border: float) -> str:
    """Assign one incident to a country from its longitude (pilot split)."""
    return "TR" if float(longitude) >= border else "GR"


def _normalize_fields(raw: Any) -> list[str]:
    """Coerce a str / sequence of tokens into an ordered, validated subset.

    Result keeps canonical :data:`SHAREABLE_FIELD_GROUPS` order and drops
    duplicates, so the same selection reads identically everywhere.
    """
    if isinstance(raw, str):
        tokens = [tok.strip().lower() for tok in raw.split(",")]
    elif isinstance(raw, Sequence):
        tokens = [str(tok).strip().lower() for tok in raw]
    else:  # pragma: no cover - defensive, callers pass str or list
        tokens = [str(raw).strip().lower()]
    chosen = [tok for tok in tokens if tok]
    unknown = [tok for tok in chosen if tok not in SHAREABLE_FIELD_GROUPS]
    if unknown:
        raise CrossborderError(
            f"unknown data-sharing field(s): {', '.join(sorted(set(unknown)))}; "
            f"valid fields are {', '.join(SHAREABLE_FIELD_GROUPS)}"
        )
    return [grp for grp in SHAREABLE_FIELD_GROUPS if grp in chosen]


def _resolve_shared_fields(settings: Any, override: Optional[Any]) -> list[str]:
    """Active sharing scope: request override else configured default."""
    raw = (
        override
        if override is not None
        else getattr(settings, "CROSSBORDER_SHARED_FIELDS", DEFAULT_SHARED_FIELDS)
    )
    return _normalize_fields(raw)


def _worst_level(levels: list[Optional[str]]) -> Optional[str]:
    """The most severe risk band present (``None`` when no risk is shared)."""
    present = [lvl for lvl in levels if lvl in RISK_LEVELS]
    if not present:
        return None
    return max(present, key=lambda lvl: RISK_LEVELS.index(lvl))


def _event_row(
    risk_event: dict[str, Any],
    support_event: Optional[dict[str, Any]],
    fields: list[str],
) -> dict[str, Any]:
    """One incident's shared view, carrying only the enabled field groups."""
    row: dict[str, Any] = {"event_key": risk_event["event_key"]}
    if "fire" in fields:
        row["fire"] = {
            "name": risk_event.get("name"),
            "latitude": risk_event.get("latitude"),
            "longitude": risk_event.get("longitude"),
            "status": risk_event.get("status"),
        }
    if "risk" in fields:
        row["risk"] = {
            "peak_level": risk_event.get("peak_level"),
            "peak_risk_index": risk_event.get("peak_risk_index"),
            "peak_horizon_minutes": risk_event.get("peak_horizon_minutes"),
        }
    if "support" in fields and support_event is not None:
        row["support"] = {
            "predicted_shortfall": support_event.get("predicted_shortfall"),
            "estimated_support_units": support_event.get("estimated_support_units"),
            "request_by_minute": support_event.get("request_by_minute"),
            "message": support_event.get("message"),
        }
    return row


def _country_block(
    country: str,
    events: list[dict[str, Any]],
    support_by_key: dict[str, dict[str, Any]],
    fields: list[str],
) -> dict[str, Any]:
    """Roll one country's incidents up to a shared summary."""
    rows = [
        _event_row(ev, support_by_key.get(ev["event_key"]), fields) for ev in events
    ]
    peak_level = (
        _worst_level([ev.get("peak_level") for ev in events])
        if "risk" in fields
        else None
    )
    support_events = [
        support_by_key[ev["event_key"]]
        for ev in events
        if ev["event_key"] in support_by_key
    ]
    total_units: Optional[int] = None
    warnings: Optional[int] = None
    if "support" in fields:
        total_units = sum(
            int(a.get("estimated_support_units") or 0) for a in support_events
        )
        warnings = sum(1 for a in support_events if a.get("predicted_shortfall"))
    return {
        "country": country,
        "label": COUNTRY_LABELS.get(country, country),
        "event_count": len(events),
        "peak_level": peak_level,
        "total_support_units": total_units,
        "events_with_support_warning": warnings,
        "events": rows,
    }


def _country_message(block: dict[str, Any]) -> str:
    """One-line, scope-aware status sentence for a country."""
    parts = [f"{block['label']}: {block['event_count']} olay"]
    if block["peak_level"] is not None:
        parts.append(f"en yüksek risk {block['peak_level']}")
    if block["total_support_units"] is not None:
        need = block["total_support_units"]
        parts.append(f"dış destek ≈ {need} birim" if need else "dış destek gerekmiyor")
    return "; ".join(parts) + "."


def crossborder_situation(
    session: Session,
    settings: Any,
    shared_fields: Optional[Any] = None,
) -> dict[str, Any]:
    """Build the shared TR/GR situation view under the active scope."""
    fields = _resolve_shared_fields(settings, shared_fields)
    border = border_longitude(settings)
    risk = compute_risk_index(session, settings)
    support = forecast_external_support(session, settings)
    support_by_key = {a["event_key"]: a for a in support.get("events", [])}

    buckets: dict[str, list[dict[str, Any]]] = {c: [] for c in COUNTRIES}
    for event in risk.get("events", []):
        country = country_for(event["longitude"], border)
        buckets.setdefault(country, []).append(event)

    countries_out = [
        _country_block(country, events, support_by_key, fields)
        for country, events in sorted(buckets.items())
        if events
    ]

    total_events = sum(block["event_count"] for block in countries_out)
    overall_peak = (
        _worst_level([b["peak_level"] for b in countries_out])
        if "risk" in fields
        else None
    )
    total_support = (
        sum(
            int(b["total_support_units"] or 0)
            for b in countries_out
            if b["total_support_units"] is not None
        )
        if "support" in fields
        else None
    )
    message = (
        "; ".join(_country_message(b) for b in countries_out)
        or "Etkin sınır ötesi yangın olayı yok."
    )

    return {
        "panel": "crossborder_situation",
        "generated_at": risk["generated_at"],
        "unit": risk["unit"],
        "border_longitude": border,
        "shared_fields": fields,
        "shareable_fields": list(SHAREABLE_FIELD_GROUPS),
        "attribution": CROSSBORDER_ATTRIBUTION,
        "persistence": "none",
        "countries": countries_out,
        "summary": {
            "countries_present": [b["country"] for b in countries_out],
            "total_events": total_events,
            "overall_peak_level": overall_peak,
            "total_support_units": total_support,
            "message": message,
        },
    }


__all__ = [
    "COUNTRIES",
    "COUNTRY_LABELS",
    "CROSSBORDER_ATTRIBUTION",
    "CrossborderError",
    "DEFAULT_SHARED_FIELDS",
    "SHAREABLE_FIELD_GROUPS",
    "border_longitude",
    "country_for",
    "crossborder_situation",
]
