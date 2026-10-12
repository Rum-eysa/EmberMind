"""High-priority silent-region alert feed (EM-040, Epic E4).

The operator wants to be pinged the moment a *risky* region goes silent so the
response is not delayed. EM-040 does not re-derive anything: it layers an
operator-facing **alert feed** on top of EM-037's graded report
(:func:`src.services.silent_region_risk.silent_region_risk_report`). Each of
EM-037's ``is_high_priority`` zones - a confidently-silent region whose
bounding box a neighbouring *active* fire's spread forecast reaches - becomes
one alert that carries the region, **how long it has been silent** and a
Turkish **risk level**. When several active fires threaten the *same* region
the duplicate alerts are **suppressed** into that single alert (EM-040
acceptance: "aynı bölge için tekrar uyarı bastırılır").

Read-only composition: nothing is written, ``persistence`` is ``none``. Silence
duration is measured from the silent-region record's ``created_at`` (when the
operator logged the blackout) to now. The feed is deterministic per request.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import SilentRegion
from src.services.silent_region_risk import silent_region_risk_report
from src.utils.timeutils import to_utc_iso, utc_now

# Risk-level ladder thresholds on EM-037's priority score (risk x silence).
DEFAULT_CRITICAL_PRIORITY = 0.6
DEFAULT_HIGH_PRIORITY = 0.4
DEFAULT_MEDIUM_PRIORITY = 0.2
DEFAULT_MAX_LIMIT = 200

RISK_LEVEL_ORDER = ("kritik", "yuksek", "orta", "dusuk")
RISK_LEVEL_LABELS = {
    "kritik": "Kritik",
    "yuksek": "Yüksek",
    "orta": "Orta",
    "dusuk": "Düşük",
}

SILENT_REGION_ALERT_ATTRIBUTION = (
    "EM-040: yüksek öncelikli sessiz bölge uyarıları, EM-037 risk x sessizlik "
    "raporunun yüksek-öncelik işaretli bölgelerinden türetilir; her bölge için "
    "tek uyarı (aynı bölgenin tekrar uyarıları bastırılır), bölge/süre/risk "
    "seviyesi taşınır"
)
SILENT_REGION_ALERT_PERSISTENCE = "none"


class SilentRegionAlertError(ValueError):
    """Raised for an invalid caller-supplied filter (mapped to HTTP 400)."""


def _critical_priority(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_ALERT_CRITICAL_PRIORITY", DEFAULT_CRITICAL_PRIORITY)
    )


def _high_priority(settings: Any) -> float:
    return float(getattr(settings, "SILENT_ALERT_HIGH_PRIORITY", DEFAULT_HIGH_PRIORITY))


def _medium_priority(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_ALERT_MEDIUM_PRIORITY", DEFAULT_MEDIUM_PRIORITY)
    )


def _max_limit(settings: Any) -> int:
    return int(getattr(settings, "SILENT_ALERT_MAX_LIMIT", DEFAULT_MAX_LIMIT))


def _risk_level(priority_score: float, settings: Any) -> tuple[str, str]:
    """Map EM-037's priority score onto the Turkish risk-level ladder."""
    if priority_score >= _critical_priority(settings):
        code = "kritik"
    elif priority_score >= _high_priority(settings):
        code = "yuksek"
    elif priority_score >= _medium_priority(settings):
        code = "orta"
    else:
        code = "dusuk"
    return code, RISK_LEVEL_LABELS[code]


def _silence_created_map(session: Session) -> dict[int, Optional[datetime]]:
    """Region id -> the moment the operator logged the silent zone."""
    result: dict[int, Optional[datetime]] = {}
    for region in session.scalars(select(SilentRegion)).all():
        created = region.created_at
        result[int(region.id)] = created if isinstance(created, datetime) else None
    return result


def _silence_duration(created: Optional[datetime], now: datetime) -> float:
    """Hours the region has been silent (``0.0`` when the record is unusable)."""
    if created is None:
        return 0.0
    delta = now - created
    return round(max(0.0, delta.total_seconds() / 3600.0), 2)


def _alert_message(row: dict[str, Any], level_label: str, hours: float) -> str:
    """Short Turkish operator alert text for one high-priority silent region."""
    days = round(hours / 24.0, 1)
    return (
        f"{row['region_name']} bölgesi {hours:.1f} saattir sessiz "
        f"({days:.1f} gün) ve aktif yangın yayılımı bölgeye ulaşıyor - "
        f"risk seviyesi {level_label}."
    )


def _build_alert(
    row: dict[str, Any],
    created_map: dict[int, Optional[datetime]],
    now: datetime,
    settings: Any,
) -> dict[str, Any]:
    """Turn one EM-037 high-priority row into a single, de-duplicated alert."""
    level_code, level_label = _risk_level(float(row["priority_score"]), settings)
    hours = _silence_duration(created_map.get(int(row["id"])), now)
    threatening = list(row["threatening_event_keys"])
    fire_count = len(threatening) if threatening else (1 if row["worst_threat"] else 0)
    # One alert per region; any extra threatening fires are suppressed here.
    suppressed = max(0, fire_count - 1)
    return {
        "alert_id": f"SA-{row['id']}",
        "region_id": row["id"],
        "region_name": row["region_name"],
        "reason": row["reason"],
        "risk_level_code": level_code,
        "risk_level_label": level_label,
        "risk_degree": row["risk_degree"],
        "silence_degree": row["silence_degree"],
        "priority_score": row["priority_score"],
        "silence_duration_hours": hours,
        "silence_duration_days": round(hours / 24.0, 2),
        "threatening_event_keys": threatening,
        "threatening_fire_count": fire_count,
        "suppressed_duplicate_alerts": suppressed,
        "worst_threat": row["worst_threat"],
        "bounding_box": {
            "min_lat": row["min_lat"],
            "max_lat": row["max_lat"],
            "min_lon": row["min_lon"],
            "max_lon": row["max_lon"],
        },
        "message": _alert_message(row, level_label, hours),
    }


def silent_region_alert_report(
    session: Session,
    settings: Any,
    *,
    level: Optional[str] = None,
    limit: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Alert feed for high-priority silent regions, most urgent first.

    ``level`` keeps only alerts whose risk level matches the requested code;
    ``limit`` clips the returned list while the summary describes the whole
    de-duplicated alert set. Repeat threats for one region are folded into a
    single alert (``suppressed_duplicate_alerts``).
    """
    if limit is not None and limit < 1:
        raise SilentRegionAlertError("limit 1 veya daha büyük olmalı")
    if level is not None and level not in RISK_LEVEL_ORDER:
        raise SilentRegionAlertError(
            "level biri olmalı: " + ", ".join(RISK_LEVEL_ORDER)
        )

    stamp = now or utc_now()
    graded = silent_region_risk_report(session, settings, flagged_only=True)
    created_map = _silence_created_map(session)

    alerts = [
        _build_alert(row, created_map, stamp, settings) for row in graded["regions"]
    ]
    # Highest priority first, then region name for a stable ordering.
    alerts.sort(key=lambda a: (-a["priority_score"], a["region_name"]))

    by_level = {code: 0 for code in RISK_LEVEL_ORDER}
    for alert in alerts:
        by_level[alert["risk_level_code"]] += 1

    raw_candidates = sum(1 + a["suppressed_duplicate_alerts"] for a in alerts)
    suppressed = raw_candidates - len(alerts)

    emitted = [a for a in alerts if level is None or a["risk_level_code"] == level]
    max_limit = _max_limit(settings)
    if limit is not None:
        emitted = emitted[: max(1, min(limit, max_limit))]

    return {
        "panel": "silent_region_alert",
        "generated_at": to_utc_iso(stamp),
        "count": len(emitted),
        "filter_level": level,
        "limit": max(1, min(limit, max_limit)) if limit is not None else None,
        "thresholds": {
            "critical_priority": _critical_priority(settings),
            "high_priority": _high_priority(settings),
            "medium_priority": _medium_priority(settings),
            "max_limit": max_limit,
        },
        "summary": {
            "high_priority_regions": len(alerts),
            "emitted_alerts": len(alerts),
            "raw_candidate_alerts": raw_candidates,
            "suppressed_duplicate_alerts": suppressed,
            "by_level": by_level,
        },
        "alerts": emitted,
        "risk_levels": [
            {"code": code, "label": RISK_LEVEL_LABELS[code]}
            for code in RISK_LEVEL_ORDER
        ],
        "attribution": SILENT_REGION_ALERT_ATTRIBUTION,
        "persistence": SILENT_REGION_ALERT_PERSISTENCE,
    }


def silent_region_alert_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: the risk-level ladder, its bands and persistence."""
    return {
        "source": "EM-037 silent_region_risk_report (flagged_only high-priority)",
        "duration_basis": "silent region created_at -> now (saat)",
        "suppression_rule": "aynı bölge için tek uyarı; ek tehditler bastırılır",
        "sort": "priority_score desc, region_name asc",
        "risk_level_ladder": [
            {"code": code, "label": RISK_LEVEL_LABELS[code]}
            for code in RISK_LEVEL_ORDER
        ],
        "thresholds": {
            "critical_priority": _critical_priority(settings),
            "high_priority": _high_priority(settings),
            "medium_priority": _medium_priority(settings),
            "max_limit": _max_limit(settings),
        },
        "attribution": SILENT_REGION_ALERT_ATTRIBUTION,
        "persistence": SILENT_REGION_ALERT_PERSISTENCE,
    }


__all__ = [
    "RISK_LEVEL_LABELS",
    "RISK_LEVEL_ORDER",
    "SILENT_REGION_ALERT_ATTRIBUTION",
    "SILENT_REGION_ALERT_PERSISTENCE",
    "SilentRegionAlertError",
    "silent_region_alert_config",
    "silent_region_alert_report",
]
