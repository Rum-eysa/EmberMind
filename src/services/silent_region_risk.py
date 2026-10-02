"""High-priority silent-region risk intersection (EM-037, Epic E4).

A *silent region* is an operator-recorded blackout / no-fire zone: no SOS, no
observed fire reported from inside it. EM-037's premise is that **silence is not
safety** - a zone that stays quiet while a neighbouring wildfire's spread
forecast is heading straight into it is exactly the case the operator must see
first ("riskli ama sessiz bölge").

This is a read-time projection that composes two pieces the codebase already
knows how to compute and writes nothing new (``persistence`` is ``none``):

* **silence degree** - the EM-078 silent-zone confidence (reused verbatim from
  :func:`src.services.silent_zone_panel.silent_zone_report`): ``1.0`` means the
  zone is genuinely uncontradicted (no active fire centre inside it), the very
  definition of "silent but unattended";
* **risk degree** - how far the EM-015 spread-forecast polygons of the *active*
  fires reach into the zone, measured as the fraction of the zone's bounding box
  covered by the worst-case forecast footprint (a Shapely intersection in the
  shared lat/lon frame).

``priority = risk_degree x silence_degree`` orders the list (EM-037 acceptance:
"list sorted by risk x silence"), and a zone whose forecast coverage clears the
configured floor *while still being confidently silent* is flagged as a
**"yüksek öncelikli sessiz bölge"** (high-priority silent region).
"""
from typing import Any, Optional

from shapely import wkt as shapely_wkt
from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.geometry import box as shapely_box
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import FireEvent, FireForecast, SilentRegion
from src.services.silent_zone_panel import silent_zone_report
from src.utils.timeutils import to_utc_iso, utc_now

ACTIVE_FIRE_STATUS = "active"

DEFAULT_MIN_COVERAGE = 0.05
DEFAULT_MIN_CONFIDENCE = 0.5
DEFAULT_MAX_FORECASTS = 200
DEFAULT_MAX_LIMIT = 200

SILENT_REGION_RISK_ATTRIBUTION = (
    "EM-037: yüksek öncelikli sessiz bölge, EM-078 sessizlik güveni ile aktif "
    "yangınların EM-015 yayılım tahmin poligonlarının bölge kutusunu kapsama "
    "oranının çarpımından türetilir; risk x sessizlik sıralı liste"
)
SILENT_REGION_RISK_PERSISTENCE = "none"


class SilentRegionRiskError(ValueError):
    """Raised for an invalid caller-supplied filter (mapped to HTTP 400)."""


def _min_coverage(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_REGION_RISK_MIN_COVERAGE", DEFAULT_MIN_COVERAGE)
    )


def _min_confidence(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_REGION_RISK_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
    )


def _max_forecasts(settings: Any) -> int:
    return int(
        getattr(settings, "SILENT_REGION_RISK_MAX_FORECASTS", DEFAULT_MAX_FORECASTS)
    )


def _max_limit(settings: Any) -> int:
    return int(getattr(settings, "SILENT_REGION_RISK_MAX_LIMIT", DEFAULT_MAX_LIMIT))


def _region_box(region: SilentRegion) -> Optional[Polygon]:
    """Bounding-box rectangle of a silent region in the shared lon/lat frame."""
    if None in (region.min_lat, region.max_lat, region.min_lon, region.max_lon):
        return None
    box = shapely_box(
        float(region.min_lon),
        float(region.min_lat),
        float(region.max_lon),
        float(region.max_lat),
    )
    if box.is_empty or box.area <= 0:
        return None
    return box


def _parse_polygon(raw_wkt: Optional[str]) -> Optional[Polygon]:
    """Parse a stored forecast WKT into a valid Shapely polygon (else ``None``)."""
    if not raw_wkt:
        return None
    try:
        geom = shapely_wkt.loads(raw_wkt)
    except (GEOSException, ValueError):
        return None
    if isinstance(geom, Polygon) and geom.is_valid and geom.area > 0:
        return geom
    return None


def _active_silent_regions(session: Session) -> list[SilentRegion]:
    return list(
        session.scalars(
            select(SilentRegion).where(SilentRegion.is_active.is_(True))
        ).all()
    )


def _threat_polygons(session: Session, max_forecasts: int) -> list[dict[str, Any]]:
    """Forecast footprints of *active* fires, as threat descriptors.

    Each stored :class:`FireForecast` is joined to its originating
    :class:`FireEvent` and kept only when that event is still ``active``; the
    polygon geometry is parsed eagerly so the caller never re-parses per region.
    """
    rows = session.execute(
        select(FireForecast, FireEvent.name, FireEvent.severity)
        .join(FireEvent, FireEvent.event_key == FireForecast.event_key)
        .where(FireEvent.status == ACTIVE_FIRE_STATUS)
        .order_by(FireForecast.created_at.desc())
        .limit(max_forecasts)
    ).all()
    threats: list[dict[str, Any]] = []
    for forecast, fire_name, fire_severity in rows:
        polygon = _parse_polygon(forecast.geometry_wkt)
        if polygon is None:
            continue
        threats.append(
            {
                "event_key": str(forecast.event_key),
                "fire_name": str(fire_name),
                "severity": str(fire_severity),
                "horizon_minutes": int(forecast.horizon_minutes or 0),
                "forecast_for": to_utc_iso(forecast.forecast_for)
                if forecast.forecast_for
                else None,
                "polygon": polygon,
            }
        )
    return threats


def _score_region(
    region: SilentRegion,
    threats: list[dict[str, Any]],
    confidence_by_id: dict[int, float],
) -> dict[str, Any]:
    """Risk x silence grading for one silent region (its worst-case threat)."""
    box = _region_box(region)
    silence = float(confidence_by_id.get(int(region.id), 0.0))

    risk_degree = 0.0
    best: Optional[dict[str, Any]] = None
    threatening: list[str] = []
    if box is not None:
        for threat in threats:
            covered = 0.0
            try:
                if box.intersects(threat["polygon"]):
                    covered = box.intersection(threat["polygon"]).area / box.area
            except GEOSException:
                covered = 0.0
            covered = max(0.0, min(1.0, float(covered)))
            if covered > 0:
                threatening.append(str(threat["event_key"]))
            if covered > risk_degree:
                risk_degree = covered
                best = threat

    risk_degree = round(risk_degree, 4)
    priority = round(risk_degree * silence, 4)
    return {
        "id": region.id,
        "region_name": region.region_name,
        "reason": region.reason,
        "min_lat": float(region.min_lat),
        "max_lat": float(region.max_lat),
        "min_lon": float(region.min_lon),
        "max_lon": float(region.max_lon),
        "risk_degree": risk_degree,
        "silence_degree": round(silence, 3),
        "priority_score": priority,
        "threatening_event_keys": sorted(set(threatening)),
        "worst_threat": (
            None
            if best is None
            else {
                "event_key": best["event_key"],
                "fire_name": best["fire_name"],
                "severity": best["severity"],
                "horizon_minutes": best["horizon_minutes"],
                "forecast_for": best["forecast_for"],
            }
        ),
    }


def _flag_row(row: dict[str, Any], min_cov: float, min_conf: float) -> dict[str, Any]:
    """Attach the derived high-priority flag + Turkish label to a graded row."""
    flagged = bool(row["risk_degree"] >= min_cov and row["silence_degree"] >= min_conf)
    row["is_high_priority"] = flagged
    row["priority_label"] = (
        "Yüksek öncelikli sessiz bölge" if flagged else "Öncelik dışı"
    )
    return row


def silent_region_risk_report(
    session: Session,
    settings: Any,
    flagged_only: bool = False,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Silent regions graded by forecast-reach risk x silence, most urgent first.

    ``flagged_only`` keeps just the ``is_high_priority`` zones; ``limit`` clips
    the returned list to ``[1, SILENT_REGION_RISK_MAX_LIMIT]`` while the summary
    counts always describe the whole graded set.
    """
    min_cov = _min_coverage(settings)
    min_conf = _min_confidence(settings)
    max_limit = _max_limit(settings)

    graded_source = silent_zone_report(session, settings)
    confidence_by_id = {
        int(zone["id"]): float(zone["confidence"]) for zone in graded_source["regions"]
    }
    threats = _threat_polygons(session, _max_forecasts(settings))

    rows: list[dict[str, Any]] = []
    for region in _active_silent_regions(session):
        scored = _score_region(region, threats, confidence_by_id)
        rows.append(_flag_row(scored, min_cov, min_conf))

    rows.sort(key=lambda r: (-r["priority_score"], r["region_name"]))
    intersecting = sum(1 for r in rows if r["risk_degree"] > 0)
    high_priority = sum(1 for r in rows if r["is_high_priority"])

    listing = [r for r in rows if r["is_high_priority"]] if flagged_only else rows
    if limit is not None:
        if limit < 1:
            raise SilentRegionRiskError("limit 1 veya daha büyük olmalı")
        listing = listing[: max(1, min(limit, max_limit))]

    return {
        "panel": "silent_region_risk",
        "generated_at": to_utc_iso(utc_now()),
        "count": len(listing),
        "flagged_only": bool(flagged_only),
        "limit": max(1, min(limit, max_limit)) if limit is not None else None,
        "thresholds": {
            "min_coverage": min_cov,
            "min_confidence": min_conf,
            "max_limit": max_limit,
        },
        "summary": {
            "active_silent_regions": len(rows),
            "intersecting_regions": intersecting,
            "high_priority_regions": high_priority,
            "active_forecast_polygons": len(threats),
        },
        "regions": listing,
        "attribution": SILENT_REGION_RISK_ATTRIBUTION,
        "persistence": SILENT_REGION_RISK_PERSISTENCE,
    }


def silent_region_risk_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: thresholds, the derivation and its persistence."""
    return {
        "formula": "priority = risk_degree x silence_degree",
        "risk_degree": "aktif yangın yayılım tahmin poligonunun bölge kutusunu "
        "kapsama oranı [0,1]",
        "silence_degree": "EM-078 sessiz bölge güveni [0,1] (içinde aktif yangın "
        "yoksa yüksek)",
        "high_priority_rule": "risk_degree >= min_coverage ve silence_degree >= "
        "min_confidence",
        "thresholds": {
            "min_coverage": _min_coverage(settings),
            "min_confidence": _min_confidence(settings),
            "max_forecasts": _max_forecasts(settings),
            "max_limit": _max_limit(settings),
        },
        "sort": "priority_score desc, region_name asc",
        "attribution": SILENT_REGION_RISK_ATTRIBUTION,
        "persistence": SILENT_REGION_RISK_PERSISTENCE,
    }


__all__ = [
    "SILENT_REGION_RISK_ATTRIBUTION",
    "SILENT_REGION_RISK_PERSISTENCE",
    "SilentRegionRiskError",
    "silent_region_risk_config",
    "silent_region_risk_report",
]
