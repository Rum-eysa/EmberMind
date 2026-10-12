"""Cross-border fire spread projection (EM-067, Epic E7).

The coordinator asks: *could this fire cross the national border, and when*
- so the neighbouring country gets an early warning instead of a surprise.
The answer is a **deterministic geometric projection** over the EM-015 head
spread, not a learned model:

* each active incident is attributed to TR (east) or GR (west) with the same
  configurable pilot border longitude as EM-066 (``CROSSBORDER_BORDER_LONGITUDE``);
* the border bearing is due west for TR incidents and due east for GR ones, and
  the centroid-to-border distance is converted with a ``cos(latitude)`` km per
  degree factor;
* the latest forecast's spread bearing (the direction the head actually moves,
  downwind + upslope) is compared to that border bearing: the cosine of the
  angle between them is the share of head movement aimed at the border -
  reported as the crossing *likelihood* (1.0 means the head drives straight at
  it; ``<= 0`` means the fire moves away and no crossing is projected);
* the crossing time is the border distance divided by the head rate of spread
  along that toward-border component (a linear projection of the current ROS -
  winds change, so it is a *projection*, flagged with whether it lands inside
  the stored forecast window).

A calm/flat fire has no bearing (circular growth): it expands in every
direction, so the toward-border share is 1.0. Nothing is persisted; the result
is derived live from the stored EM-015 forecasts.
"""
import math
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import FireEvent, FireForecast
from src.services.crossborder_situation import (
    COUNTRY_LABELS,
    border_longitude,
    country_for,
)
from src.utils.timeutils import to_utc_iso, utc_now

SPREAD_ATTRIBUTION = (
    "Sınır geçiş projeksiyonu: EM-015 baş yayılım yönü/hızı / "
    "EM-066 pilot sınır boylamı (deterministik geometri)"
)
# Approximate km per degree of longitude at the equator; scaled by
# cos(latitude) for the pilot's ~36-39.5 N band.
_KM_PER_DEG_LON = 111.320
# Likelihood bands on the toward-border share of head movement.
_HIGH_LIKELIHOOD = 0.75
_MED_LIKELIHOOD = 0.40


def _likelihood_level(likelihood: Optional[float]) -> str:
    """Turkish band label for a toward-border share (None: no forecast)."""
    if likelihood is None:
        return "belirsiz"
    if likelihood <= 0.0:
        return "yok"
    if likelihood < _MED_LIKELIHOOD:
        return "düşük"
    if likelihood < _HIGH_LIKELIHOOD:
        return "orta"
    return "yüksek"


def _latest_forecasts(session: Session) -> dict[str, FireForecast]:
    """Newest stored forecast row per event (its bearing/ROS describe the run)."""
    latest: dict[str, FireForecast] = {}
    rows = session.scalars(
        select(FireForecast).order_by(FireForecast.id.desc()).limit(2000)
    )
    for row in rows:
        key = str(row.event_key)
        if key not in latest:
            latest[key] = row
    return latest


def _bearing_to_border(longitude: float, border: float) -> float:
    """Due west (270) for east-side incidents, due east (90) for west-side."""
    return 270.0 if longitude >= border else 90.0


def _angle_alignment(direction_deg: Optional[float], bearing_deg: float) -> float:
    """Share of head movement aimed at the border, in ``[-1, 1]``.

    ``cos`` of the signed angle between the spread bearing and the border
    bearing; a fire with no bearing grows circularly, hitting the border
    direction fully (1.0).
    """
    if direction_deg is None:
        return 1.0
    delta = math.radians((float(direction_deg) - bearing_deg + 180.0) % 360.0 - 180.0)
    return math.cos(delta)


def _message(
    likelihood: Optional[float],
    minutes: Optional[float],
    target: str,
    window: bool,
) -> str:
    """Early-warning sentence for one incident (Turkish, panel style)."""
    label = COUNTRY_LABELS.get(target, target)
    if likelihood is None:
        return "Yayılım tahmini yok; sınır geçiş projeksiyonu üretilemedi."
    if minutes is None or likelihood <= 0.0:
        return (
            f"Sınır geçişi öngörülmüyor — baş yayılım {label} sınırının "
            "aksi yönünde."
        )
    timing = " (öngörü penceresi içinde)" if window else " (öngörü penceresi dışı)"
    return (
        f"Yangın ~T+{int(round(minutes))} dk sonra {label} sınırını "
        f"geçebilir (olasılık ≈ {likelihood:.2f}){timing}."
    )


def _assess_event(
    event: FireEvent,
    forecast: Optional[FireForecast],
    border: float,
    window_minutes: int,
) -> dict[str, Any]:
    """Project one incident against the border: likelihood + crossing time."""
    longitude = float(event.longitude)
    latitude = float(event.latitude)
    country = country_for(longitude, border)
    target = "GR" if country == "TR" else "TR"
    distance_km = (
        abs(longitude - border) * _KM_PER_DEG_LON * math.cos(math.radians(latitude))
    )
    row: dict[str, Any] = {
        "event_key": str(event.event_key),
        "name": str(event.name),
        "country": country,
        "target_country": target,
        "distance_km": round(distance_km, 2),
        "likelihood": None,
        "likelihood_level": "belirsiz",
        "crossing_minutes": None,
        "within_forecast_window": False,
        "spread_direction_deg": None,
        "rate_of_spread_m_per_min": None,
    }
    if forecast is None:
        row["message"] = _message(None, None, target, False)
        return row

    direction = forecast.spread_direction_deg
    ros = max(0.0, float(forecast.rate_of_spread_m_per_min))
    alignment = _angle_alignment(
        None if direction is None else float(direction),
        _bearing_to_border(longitude, border),
    )
    likelihood = round(max(0.0, alignment), 2)
    minutes: Optional[float] = None
    # Gate on the rounded share so a purely perpendicular bearing (cos ~ 1e-17
    # floating-point noise at 90 degrees) never projects a spurious crossing.
    if likelihood > 0.0 and ros > 0.0:
        minutes = round(distance_km * 1000.0 / (ros * alignment), 1)
    row.update(
        {
            "likelihood": likelihood,
            "likelihood_level": _likelihood_level(likelihood),
            "crossing_minutes": minutes,
            "within_forecast_window": bool(
                minutes is not None and minutes <= window_minutes
            ),
            "spread_direction_deg": (
                None if direction is None else round(float(direction), 1)
            ),
            "rate_of_spread_m_per_min": round(ros, 2),
        }
    )
    row["message"] = _message(
        likelihood, minutes, target, bool(row["within_forecast_window"])
    )
    return row


def project_border_crossing(session: Session, settings: Any) -> dict[str, Any]:
    """Project every active incident against the pilot border (or none)."""
    border = border_longitude(settings)
    horizons = [
        int(h) for h in getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
    ]
    window_minutes = max(horizons) if horizons else 120
    events = list(
        session.scalars(
            select(FireEvent).where(FireEvent.status == "active").order_by(FireEvent.id)
        )
    )
    forecasts = _latest_forecasts(session)
    rows = [
        _assess_event(
            event, forecasts.get(str(event.event_key)), border, window_minutes
        )
        for event in events
    ]
    crossings = [r for r in rows if r["crossing_minutes"] is not None]
    soonest = min(crossings, key=lambda r: r["crossing_minutes"], default=None)
    return {
        "panel": "crossborder_spread",
        "generated_at": to_utc_iso(utc_now()),
        "border_longitude": border,
        "forecast_window_minutes": window_minutes,
        "attribution": SPREAD_ATTRIBUTION,
        "persistence": "none",
        "events": rows,
        "summary": {
            "events_scored": len(rows),
            "crossings_predicted": len(crossings),
            "earliest_crossing_event": soonest["event_key"] if soonest else None,
            "earliest_crossing_minutes": soonest["crossing_minutes"]
            if soonest
            else None,
            "message": soonest["message"]
            if soonest
            else "Aktif olaylar için sınır geçişi öngörülmüyor.",
        },
    }


__all__ = [
    "SPREAD_ATTRIBUTION",
    "project_border_crossing",
]
