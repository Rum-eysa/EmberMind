"""Read-only municipality monitoring view (EM-083, Epic E8).

A municipal manager is not the incident commander. They want one simplified,
*monitoring-only* screen for their area - what is burning near me, how serious
it is and whether help is on station - without the operator console's decision
controls, what-if sliders or dispatch actions (EM-083 acceptance: "a
simplified, monitoring-only screen for P5"). The full operator data already
exists in ``fire_events`` and ``suppression_resources``; what was missing was a
narrowed, read-only projection that strips the console down to essentials.

This service is a **read-time projection** (``persistence`` is ``none`` - no new
table, no migration). It scopes the survey to a configurable region bounding box
(defaults to the pilot region) and returns only the simplified essentials:

* the active fires inside the region, ordered most-severe first, with a
  deliberately small field set (key, name, severity, when it started, position);
* a severity histogram and a single headline status;
* how many suppression units are locally available vs committed inside the same
  box, plus the whole-pool counts for context.

Every operator-only affordance (recommendations, decision actions, what-if,
dispatch) is intentionally *absent* - the ``omitted_operator_controls`` list in
the config payload names exactly what was hidden, so the reduced surface is an
explicit, auditable decision rather than an accident. The result is fully
deterministic: the same data always yields the same ordering and counts.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent
from src.utils.timeutils import to_utc_iso, utc_now

# Severity ranking drives both the fire ordering and the headline status. Higher
# rank is more urgent; anything unknown ranks lowest so it never outranks a known
# value. SEVERITY_ORDER is the same set ordered most-to-least urgent.
_SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
SEVERITY_ORDER = ("critical", "high", "medium", "low")

# Unit-status vocabularies (EM-031). "available" is local capacity on station;
# "en_route"/"deployed" are the committed (spoken-for) statuses.
_AVAILABLE_STATUSES = frozenset({"available"})
_BUSY_STATUSES = frozenset({"en_route", "deployed"})

# Upper bound on how many fires the simplified screen lists (most-severe first).
MAX_FIRES = 100

# Pilot-region bounding-box defaults (mirrors config/pilot_region.json). Used only
# when a settings object omits the keys entirely (tests pass a light namespace);
# the real config always provides these values.
_DEFAULT_REGION_NAME = "TR-GR Coastal Wildfire Pilot Region"
_DEFAULT_MIN_LAT = 36.0
_DEFAULT_MAX_LAT = 39.5
_DEFAULT_MIN_LON = 26.0
_DEFAULT_MAX_LON = 30.0

# Operator-only affordances deliberately hidden from this simplified screen so a
# municipal reader sees status, not controls. Named in the config payload so the
# reduction is explicit and auditable.
OMITTED_OPERATOR_CONTROLS = (
    "recommendations",
    "decision_actions",
    "whatif_scenarios",
    "resource_dispatch",
)

MUNICIPALITY_VIEW_ATTRIBUTION = (
    "EM-083: salt okunur belediye görünümü - bölge kutusu içindeki aktif "
    "yangınlar ve yerel kaynak durumu sadeleştirilmiş, yalnızca izleme amaçlı bir "
    "projeksiyon olarak okuma zamanı derlenir; operatör karar kontrolleri bilinçli "
    "olarak gizlenir"
)
MUNICIPALITY_VIEW_PERSISTENCE = "none"
MUNICIPALITY_VIEW_READ_ONLY = True


def _rank(severity: Any) -> int:
    """Map a severity string to its urgency rank (unknown -> lowest)."""
    return _SEVERITY_RANK.get(str(severity).strip().lower(), 0)


def _region_box(settings: Any) -> dict[str, Any]:
    """The configured region bounding box (defaults to the pilot region)."""
    return {
        "name": str(
            getattr(settings, "MUNICIPALITY_VIEW_REGION_NAME", _DEFAULT_REGION_NAME)
        ),
        "min_lat": float(
            getattr(settings, "MUNICIPALITY_VIEW_MIN_LAT", _DEFAULT_MIN_LAT)
        ),
        "max_lat": float(
            getattr(settings, "MUNICIPALITY_VIEW_MAX_LAT", _DEFAULT_MAX_LAT)
        ),
        "min_lon": float(
            getattr(settings, "MUNICIPALITY_VIEW_MIN_LON", _DEFAULT_MIN_LON)
        ),
        "max_lon": float(
            getattr(settings, "MUNICIPALITY_VIEW_MAX_LON", _DEFAULT_MAX_LON)
        ),
    }


def _in_box(lat: float, lon: float, box: dict[str, Any]) -> bool:
    """True when a coordinate falls inside the region bounding box."""
    return (
        box["min_lat"] <= lat <= box["max_lat"]
        and box["min_lon"] <= lon <= box["max_lon"]
    )


def _max_fires(settings: Any) -> int:
    """Positive fire-list cap from settings, falling back to ``MAX_FIRES``."""
    try:
        want = int(getattr(settings, "MUNICIPALITY_VIEW_MAX_FIRES", MAX_FIRES))
    except (TypeError, ValueError):
        return MAX_FIRES
    return max(1, want)


def _active_fires(session: Session, box: dict[str, Any]) -> list[FireEvent]:
    """Active fires whose centroid is inside the region box."""
    rows = session.scalars(select(FireEvent).where(FireEvent.status == "active")).all()
    inside = [
        row for row in rows if _in_box(float(row.latitude), float(row.longitude), box)
    ]
    inside.sort(key=lambda r: (-_rank(r.severity), str(r.started_at), r.event_key))
    return inside


def _fire_row(event: FireEvent) -> dict[str, Any]:
    """One active fire, simplified to the monitoring essentials."""
    return {
        "event_key": str(event.event_key),
        "name": str(event.name),
        "severity": str(event.severity),
        "severity_rank": _rank(event.severity),
        "started_at": to_utc_iso(event.started_at)
        if isinstance(event.started_at, datetime)
        else None,
        "latitude": round(float(event.latitude), 4),
        "longitude": round(float(event.longitude), 4),
    }


def _unit_counts(session: Session, box: dict[str, Any]) -> tuple[int, int, int, int]:
    """(local_available, local_committed, pool_available, pool_committed).

    Local counts respect the region box; pool counts cover the whole inventory so
    a municipal reader still sees how much of the shared resource base sits
    outside their area.
    """
    rows = session.scalars(select(SuppressionResource)).all()
    local_available = 0
    local_committed = 0
    pool_available = 0
    pool_committed = 0
    for row in rows:
        status = str(row.status)
        if status in _AVAILABLE_STATUSES:
            pool_available += 1
            if _in_box(float(row.latitude), float(row.longitude), box):
                local_available += 1
        elif status in _BUSY_STATUSES:
            pool_committed += 1
            if _in_box(float(row.latitude), float(row.longitude), box):
                local_committed += 1
    return local_available, local_committed, pool_available, pool_committed


def municipality_view(
    session: Session, settings: Any, *, severity: Optional[str] = None
) -> dict[str, Any]:
    """Build the simplified, read-only monitoring projection for the region.

    An optional ``severity`` narrows the listed fires to one severity band; the
    headline and capacity snapshot stay region-wide so the screen never hides a
    more serious incident behind a filter. ``severity`` is validated: an unknown
    code is reported back (``requested_severity``) but does not silently filter
    everything out.
    """
    box = _region_box(settings)
    limit = _max_fires(settings)

    fires = _active_fires(session, box)
    severity_counts = {code: 0 for code in SEVERITY_ORDER}
    for event in fires:
        code = str(event.severity).strip().lower()
        if code in severity_counts:
            severity_counts[code] += 1

    requested = severity.strip().lower() if severity else None
    known = requested in _SEVERITY_RANK if requested is not None else False
    shown = fires
    if requested is not None and known:
        shown = [e for e in fires if str(e.severity).strip().lower() == requested]

    listed = shown[:limit]

    most_severe: Optional[str] = None
    for event in fires:
        code = str(event.severity).strip().lower()
        if most_severe is None or _rank(code) > _rank(most_severe):
            most_severe = code

    (
        local_available,
        local_committed,
        pool_available,
        pool_committed,
    ) = _unit_counts(session, box)

    return {
        "panel": "municipality_view",
        "read_only": MUNICIPALITY_VIEW_READ_ONLY,
        "region": box,
        "fires": [_fire_row(e) for e in listed],
        "fire_count": len(listed),
        "active_fire_total": len(fires),
        "filter": {
            "severity": requested if known else None,
            "requested_severity": requested,
            "severity_recognised": bool(known) if requested is not None else True,
        },
        "severity_counts": severity_counts,
        "headline": {
            "active_fire_count": len(fires),
            "most_severe": most_severe,
            "status": "aktif yangın var" if fires else "bölgede aktif yangın yok",
        },
        "capacity": {
            "local_available_units": local_available,
            "local_committed_units": local_committed,
            "pool_available_units": pool_available,
            "pool_committed_units": pool_committed,
        },
        "max_fires": limit,
        "generated_at": to_utc_iso(utc_now()),
        "attribution": MUNICIPALITY_VIEW_ATTRIBUTION,
        "persistence": MUNICIPALITY_VIEW_PERSISTENCE,
    }


def municipality_view_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: region box, vocabularies and hidden controls."""
    return {
        "panel": "municipality_view",
        "read_only": MUNICIPALITY_VIEW_READ_ONLY,
        "region": _region_box(settings),
        "severities": list(SEVERITY_ORDER),
        "available_statuses": sorted(_AVAILABLE_STATUSES),
        "busy_statuses": sorted(_BUSY_STATUSES),
        "omitted_operator_controls": list(OMITTED_OPERATOR_CONTROLS),
        "sources": [
            "fire_events (active, EM-005)",
            "suppression_resources (status, EM-008)",
        ],
        "max_fires": _max_fires(settings) if settings is not None else MAX_FIRES,
        "attribution": MUNICIPALITY_VIEW_ATTRIBUTION,
        "persistence": MUNICIPALITY_VIEW_PERSISTENCE,
    }


__all__ = [
    "MAX_FIRES",
    "MUNICIPALITY_VIEW_ATTRIBUTION",
    "MUNICIPALITY_VIEW_PERSISTENCE",
    "MUNICIPALITY_VIEW_READ_ONLY",
    "OMITTED_OPERATOR_CONTROLS",
    "SEVERITY_ORDER",
    "municipality_view",
    "municipality_view_config",
]
