"""Silent-zone confidence panel (EM-078, Epic E8).

A *silent region* (Sessiz Bölge) is an operator-recorded blackout / no-fire zone.
The operator wants to focus on the zones they can actually trust to be quiet and
de-prioritise the ones that are questionable, so this panel grades every active
silent region with a deterministic **confidence** score and lets them filter the
sorted list by confidence band and select a zone on the map (EM-078 acceptance:
"high/low confidence filters, sorted list, map-synced selection").

The score is derived from live spatial data - no learned model, nothing new is
written (the regions themselves already live in ``silent_regions``; the panel is
a read-time projection, so ``persistence`` is ``none``):

* start at ``1.0`` (an uncontradicted zone is confidently silent);
* each **active fire whose centre falls inside the zone** is a direct
  contradiction and knocks a large fixed penalty off (a "silent" zone that
  actually holds a fire is the least trustworthy);
* a **proximity penalty** scales with how close the nearest active fire is to the
  zone centroid (a zone bordering a fire is less reliably quiet than one far away);
* the result is clamped to ``[0, 1]`` and bucketed into ``high`` / ``moderate`` /
  ``low`` bands by the configured cut-offs.
"""
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import FireEvent, SilentRegion
from src.services.auto_recompute import haversine_km

ACTIVE_FIRE_STATUS = "active"
CONFIDENCE_BANDS = ("high", "moderate", "low")
BAND_LABELS = {"high": "Yüksek", "moderate": "Orta", "low": "Düşük"}

OVERLAP_PENALTY = 0.6
PROXIMITY_MAX_PENALTY = 0.35

DEFAULT_HIGH_CUTOFF = 0.75
DEFAULT_MODERATE_CUTOFF = 0.40
DEFAULT_PROXIMITY_FAR_KM = 25.0

SILENT_ZONE_ATTRIBUTION = (
    "EM-078: sessiz bölge güveni aktif yangın çakışması + en yakın yangın "
    "yakınlığından türetilir; yüksek/orta/düşük bant filtresi, sıralı liste"
)
SILENT_ZONE_PERSISTENCE = "none"


def _high_cutoff(settings: Any) -> float:
    return float(getattr(settings, "SILENT_ZONE_HIGH_CONFIDENCE", DEFAULT_HIGH_CUTOFF))


def _moderate_cutoff(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_ZONE_MODERATE_CONFIDENCE", DEFAULT_MODERATE_CUTOFF)
    )


def _proximity_far_km(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_ZONE_PROXIMITY_FAR_KM", DEFAULT_PROXIMITY_FAR_KM)
    )


def _band(confidence: float, high: float, moderate: float) -> str:
    if confidence >= high:
        return "high"
    if confidence >= moderate:
        return "moderate"
    return "low"


def _point_in_bbox(lat: float, lon: float, region: SilentRegion) -> bool:
    """True when a fire centre falls inside the region's bounding box."""
    return float(region.min_lat) <= lat <= float(region.max_lat) and float(
        region.min_lon
    ) <= lon <= float(region.max_lon)


def _active_fires(session: Session) -> list[tuple[float, float]]:
    """``(lat, lon)`` for every active fire event (the contradicting evidence)."""
    rows = session.scalars(
        select(FireEvent).where(FireEvent.status == ACTIVE_FIRE_STATUS)
    ).all()
    return [
        (float(r.latitude), float(r.longitude))
        for r in rows
        if r.latitude is not None and r.longitude is not None
    ]


def _score_region(
    region: SilentRegion,
    fires: list[tuple[float, float]],
    proximity_far_km: float,
) -> dict[str, Any]:
    """Confidence score + supporting detail for one silent region."""
    centroid_lat = (float(region.min_lat) + float(region.max_lat)) / 2.0
    centroid_lon = (float(region.min_lon) + float(region.max_lon)) / 2.0

    overlapping = [
        (lat, lon) for (lat, lon) in fires if _point_in_bbox(lat, lon, region)
    ]
    confidence = 1.0 - OVERLAP_PENALTY * len(overlapping)

    nearest_km: Optional[float] = None
    if fires:
        nearest_km = round(
            min(
                haversine_km(centroid_lat, centroid_lon, lat, lon) for lat, lon in fires
            ),
            3,
        )
    if nearest_km is not None and nearest_km < proximity_far_km:
        # linear: 0 km -> full penalty, at/over ``proximity_far_km`` -> none.
        confidence -= PROXIMITY_MAX_PENALTY * (1.0 - nearest_km / proximity_far_km)
    confidence = max(0.0, round(confidence, 3))

    return {
        "id": region.id,
        "region_name": region.region_name,
        "reason": region.reason,
        "min_lat": float(region.min_lat),
        "max_lat": float(region.max_lat),
        "min_lon": float(region.min_lon),
        "max_lon": float(region.max_lon),
        "centroid_lat": round(centroid_lat, 6),
        "centroid_lon": round(centroid_lon, 6),
        "overlapping_fire_count": len(overlapping),
        "nearest_fire_km": nearest_km,
        "confidence": confidence,
    }


def silent_zone_report(
    session: Session,
    settings: Any,
    confidence: Optional[str] = None,
) -> dict[str, Any]:
    """Confidence-graded, sorted silent-zone list with optional band filter.

    ``confidence`` (``high``/``moderate``/``low``) keeps only that band; an
    unknown value is reported back (rather than silently returning everything)
    via ``filter`` while the unfiltered list is returned so the caller can see
    the mistake. Regions are always sorted by confidence descending (most
    trustworthy first), name ascending as a stable tie-break.
    """
    high = _high_cutoff(settings)
    moderate = _moderate_cutoff(settings)
    far_km = _proximity_far_km(settings)

    regions = session.scalars(
        select(SilentRegion).where(SilentRegion.is_active.is_(True))
    ).all()
    fires = _active_fires(session)

    graded: list[dict[str, Any]] = []
    for region in regions:
        scored = _score_region(region, fires, far_km)
        scored["confidence_band"] = _band(scored["confidence"], high, moderate)
        scored["confidence_label"] = BAND_LABELS[scored["confidence_band"]]
        graded.append(scored)

    band_counts = {band: 0 for band in CONFIDENCE_BANDS}
    for row in graded:
        band_counts[row["confidence_band"]] += 1

    graded.sort(key=lambda r: (-r["confidence"], r["region_name"]))
    applied = confidence.strip().lower() if confidence else None
    valid_filter = applied in CONFIDENCE_BANDS
    listing = (
        [r for r in graded if r["confidence_band"] == applied]
        if valid_filter
        else graded
    )

    return {
        "panel": "silent_zone_panel",
        "count": len(listing),
        "count_active_regions": len(graded),
        "filter": applied if valid_filter else None,
        "requested_filter": applied,
        "band_counts": band_counts,
        "thresholds": {
            "high_cutoff": high,
            "moderate_cutoff": moderate,
            "proximity_far_km": far_km,
            "overlap_penalty": OVERLAP_PENALTY,
            "proximity_max_penalty": PROXIMITY_MAX_PENALTY,
        },
        "active_fire_count": len(fires),
        "regions": listing,
        "attribution": SILENT_ZONE_ATTRIBUTION,
        "persistence": SILENT_ZONE_PERSISTENCE,
    }


def zone_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: bands, cut-offs and the derivation the panel uses."""
    high = _high_cutoff(settings)
    moderate = _moderate_cutoff(settings)
    return {
        "bands": [
            {"code": "high", "label": BAND_LABELS["high"], "min_confidence": high},
            {
                "code": "moderate",
                "label": BAND_LABELS["moderate"],
                "min_confidence": moderate,
            },
            {"code": "low", "label": BAND_LABELS["low"], "min_confidence": 0.0},
        ],
        "proximity_far_km": _proximity_far_km(settings),
        "overlap_penalty": OVERLAP_PENALTY,
        "proximity_max_penalty": PROXIMITY_MAX_PENALTY,
        "sort": "confidence desc, region_name asc",
        "attribution": SILENT_ZONE_ATTRIBUTION,
        "persistence": SILENT_ZONE_PERSISTENCE,
    }


__all__ = [
    "BAND_LABELS",
    "CONFIDENCE_BANDS",
    "SILENT_ZONE_ATTRIBUTION",
    "SILENT_ZONE_PERSISTENCE",
    "silent_zone_report",
    "zone_config",
]
