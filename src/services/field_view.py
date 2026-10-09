"""Mobile/tablet field view (EM-084, Epic E8).

A field team leader standing on the fireline wants two things on a phone, in one
glance and without going back to the command post (EM-084 acceptance: "the field
team can read its task card and the nearby risk zone on a phone"). The desktop
operator surfaces already carry each half separately - the EM-051 task card and
the EM-029 risk index - but neither is a compact, proximity-aware answer to
"what is my job and how close is the danger, from here?".

This module is the deterministic, read-only projection that composes those two
existing engines into a single phone-legible payload:

* the team's committed task cards (EM-051), optionally narrowed to one resource
  or one incident;
* the active risk zones ranked by great-circle distance from the team's
  reference point, capped to a configurable radius and item count (EM-029).

The reference point is the team's own coordinates when supplied, otherwise the
target of its first task card - the same origin a leader reasons from. Nothing
is stored: cards come from the EM-047 decision audit and risk from the live
forecast, both recomputed on every request, so ``persistence`` is ``none``.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.services.auto_recompute import haversine_km
from src.services.risk_index import (
    RISK_LEVELS,
    RiskIndexError,
    compute_risk_index,
)
from src.services.task_instruction import (
    TASK_CARD_ATTRIBUTION,
    TaskInstructionError,
    generate_task_cards,
)
from src.utils.timeutils import to_utc_iso, utc_now

FIELD_VIEW_ATTRIBUTION = (
    "EM-084: saha ekibinin telefonundan okuyabileceği kompakt görünüm — "
    "görev kartı (EM-051) + konuma göre mesafe sıralı yakın risk bölgesi "
    "(EM-029). Deterministik, salt-okunur; yeni kalıcılık yok."
)
FIELD_VIEW_PERSISTENCE = "none"

# Proximity defaults, overridable via settings so a region can widen the ring
# without a code change. Bounds keep a stray request from fanning out unbounded.
DEFAULT_RADIUS_KM = 25.0
MAX_RADIUS_KM = 500.0
DEFAULT_MAX_ITEMS = 5
MAX_ITEMS_CAP = 50

# Reference-point sources, named so the UI can tell the leader where "buradan"
# ("from here") was measured from.
_ORIGIN_COORDS = "coordinates"
_ORIGIN_CARD = "task_card_target"
_ORIGIN_NONE = "none"


class FieldViewError(ValueError):
    """Raised when a field view cannot be anchored (no cards and no location)."""


def _radius_km(settings: Any) -> float:
    """Configured proximity radius, clamped to a sane band."""
    raw = getattr(settings, "FIELD_VIEW_RADIUS_KM", DEFAULT_RADIUS_KM)
    return max(0.1, min(float(raw), MAX_RADIUS_KM))


def _max_items(settings: Any) -> int:
    """Configured cap on nearby risk zones, clamped to ``[1, MAX_ITEMS_CAP]``."""
    raw = getattr(settings, "FIELD_VIEW_MAX_ITEMS", DEFAULT_MAX_ITEMS)
    return max(1, min(int(raw), MAX_ITEMS_CAP))


def _resolve_reference(
    latitude: Optional[float],
    longitude: Optional[float],
    cards: list[dict[str, Any]],
) -> tuple[Optional[float], Optional[float], str]:
    """Pick the point the team reasons from: its coords, else its first target."""
    if latitude is not None and longitude is not None:
        return float(latitude), float(longitude), _ORIGIN_COORDS
    if cards:
        target = cards[0].get("target") or {}
        lat = target.get("latitude")
        lon = target.get("longitude")
        if lat is not None and lon is not None:
            return float(lat), float(lon), _ORIGIN_CARD
    return None, None, _ORIGIN_NONE


def _nearby_risks(
    session: Session,
    settings: Any,
    ref_lat: Optional[float],
    ref_lon: Optional[float],
    radius_km: float,
    max_items: int,
) -> list[dict[str, Any]]:
    """Active risk zones within ``radius_km`` of the reference, nearest first."""
    if ref_lat is None or ref_lon is None:
        return []
    try:
        scored = compute_risk_index(session, settings)["events"]
    except RiskIndexError:
        return []
    ranked: list[dict[str, Any]] = []
    for event in scored:
        distance = haversine_km(ref_lat, ref_lon, event["latitude"], event["longitude"])
        if distance > radius_km:
            continue
        ranked.append(
            {
                "event_key": event["event_key"],
                "name": event["name"],
                "status": event["status"],
                "latitude": event["latitude"],
                "longitude": event["longitude"],
                "distance_km": round(distance, 2),
                "bearing_deg": _bearing_deg(
                    ref_lat, ref_lon, event["latitude"], event["longitude"]
                ),
                "peak_risk_index": event["peak_risk_index"],
                "peak_level": event["peak_level"],
                "peak_horizon_minutes": event["peak_horizon_minutes"],
            }
        )
    ranked.sort(key=lambda row: (row["distance_km"], str(row["event_key"])))
    return ranked[:max_items]


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[float]:
    """Initial great-circle bearing (deg from north, 0-360) to a nearby zone.

    ``None`` when the two points coincide, so the caller can fall back to the
    distance alone rather than showing a meaningless direction.
    """
    if lat1 == lat2 and lon1 == lon2:
        return None
    d_lon = math.radians(lon2 - lon1)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    y = math.sin(d_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        d_lon
    )
    if x == 0.0 and y == 0.0:
        return None
    return round((math.degrees(math.atan2(y, x)) + 360.0) % 360.0, 1)


def field_view(
    session: Session,
    settings: Any,
    *,
    resource_key: Optional[str] = None,
    event_key: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> dict[str, Any]:
    """Compact field view: this team's task card(s) plus the nearest risk zones.

    ``event_key`` anchors the request to one incident (an unknown incident raises
    :class:`FieldViewError`); ``resource_key`` narrows the cards to one unit; an
    explicit ``latitude``/``longitude`` overrides where "nearby" is measured
    from, otherwise the team's first task-card target is used. With no cards and
    no location the view is legitimately empty (the UI shows its empty state) -
    only an unknown incident is an error.
    """
    try:
        cards = generate_task_cards(session, settings, event_key)
    except TaskInstructionError as exc:
        raise FieldViewError(str(exc)) from exc
    if resource_key:
        cards = [c for c in cards if str(c.get("resource_key")) == str(resource_key)]

    radius_km = _radius_km(settings)
    max_items = _max_items(settings)
    ref_lat, ref_lon, origin = _resolve_reference(latitude, longitude, cards)

    nearby = _nearby_risks(session, settings, ref_lat, ref_lon, radius_km, max_items)
    return {
        "panel": "field_view",
        "generated_at": to_utc_iso(utc_now()),
        "reference": {
            "latitude": ref_lat,
            "longitude": ref_lon,
            "origin": origin,
        },
        "resource_key": resource_key,
        "event_key": event_key,
        "cards": cards,
        "nearby_risks": nearby,
        "radius_km": radius_km,
        "max_items": max_items,
        "card_count": len(cards),
        "nearby_count": len(nearby),
        "attribution": FIELD_VIEW_ATTRIBUTION,
        "card_attribution": TASK_CARD_ATTRIBUTION,
        "persistence": FIELD_VIEW_PERSISTENCE,
    }


def field_view_config(settings: Any = None) -> dict[str, Any]:
    """Knobs the mobile view needs: proximity radius, item cap, data sources."""
    radius = getattr(settings, "FIELD_VIEW_RADIUS_KM", DEFAULT_RADIUS_KM)
    max_items = getattr(settings, "FIELD_VIEW_MAX_ITEMS", DEFAULT_MAX_ITEMS)
    return {
        "panel": "field_view",
        "radius_km": _radius_km(settings)
        if settings is not None
        else DEFAULT_RADIUS_KM,
        "max_items": int(max_items),
        "sources": {
            "task_cards": "EM-051 (accepted positioning proposals)",
            "risk_zones": "EM-029 (risk index, active events)",
            "reference": "explicit coordinates, else the team's first target",
        },
        "configurable": {
            "radius_km_range": [0.1, MAX_RADIUS_KM],
            "max_items_range": [1, MAX_ITEMS_CAP],
        },
        "risk_levels": list(RISK_LEVELS),
        "attribution": FIELD_VIEW_ATTRIBUTION,
        "persistence": FIELD_VIEW_PERSISTENCE,
    }


__all__ = [
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_RADIUS_KM",
    "FIELD_VIEW_ATTRIBUTION",
    "FIELD_VIEW_PERSISTENCE",
    "MAX_ITEMS_CAP",
    "MAX_RADIUS_KM",
    "FieldViewError",
    "field_view",
    "field_view_config",
]
