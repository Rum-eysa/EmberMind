"""Cross-border display standardization (EM-063, Epic E7).

Timestamps are persisted and serialised in UTC (see :mod:`src.utils.timeutils`);
this module is the *presentation* layer an operator who watches two countries
(Turkey / Greece) needs so nobody mis-reads a clock, a unit or a coordinate:

* a UTC instant rendered in the viewer's local zone (TRT / EET, any IANA zone);
* the fixed **metric** unit system described once so both sides agree;
* a wind bearing turned into degrees **and** a compass label;
* a WGS-84 coordinate formatted either as decimal degrees or DMS.

Everything is read-only and derived live from the request parameters; nothing is
stored, so a change of preference needs no migration. ``persistence`` is
therefore reported as ``none``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The pilot spans Turkey (TRT, UTC+3) and Greece (EET/EEST); these are the
# guaranteed defaults surfaced to the UI, but any valid IANA zone is accepted.
SUPPORTED_TIMEZONES = ("Europe/Istanbul", "Europe/Athens", "UTC")
DEFAULT_TIMEZONE = "Europe/Istanbul"
COORDINATE_FORMATS = ("decimal", "dms")
DEFAULT_COORDINATE_FORMAT = "decimal"

# EM-063 fixes the metric system; this single descriptor is rendered by the UI
# so both countries read the same units everywhere.
UNITS: dict[str, str] = {
    "system": "metric",
    "distance": "km",
    "area": "ha",
    "speed": "km/h",
    "wind_direction": "degrees + compass",
    "coordinate": "WGS84 (decimal degrees / DMS)",
    "time_basis": "UTC stored, local displayed",
}

# 16-point compass, international (meteorology / ISO) abbreviations.
_COMPASS_16 = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)
_COMPASS_FULL = (
    "North",
    "North-northeast",
    "Northeast",
    "East-northeast",
    "East",
    "East-southeast",
    "Southeast",
    "South-southeast",
    "South",
    "South-southwest",
    "Southwest",
    "West-southwest",
    "West",
    "West-northwest",
    "Northwest",
    "North-northwest",
)

LOCALIZATION_ATTRIBUTION = (
    "EM-063: UTC saklanır, operatörün yerel saatinde gösterilir; birimler "
    "metriktir (km/ha/km-sa); rüzgâr yönü derece + pusula; koordinat gösterim "
    "formatı ayarlanabilir (ondalık / DMS)."
)
LOCALIZATION_PERSISTENCE = "none"


class LocalizationError(ValueError):
    """Raised for an invalid time zone, coordinate or display format."""


def _normalize_text(value: Optional[str], fallback: str) -> str:
    """Trim a possibly-``None`` value to text, substituting ``fallback``."""
    text = (value or "").strip()
    return text or fallback


def resolve_zone(tz_name: Optional[str]) -> ZoneInfo:
    """Return a :class:`ZoneInfo` for ``tz_name`` (empty -> default).

    Raises :class:`LocalizationError` for an unknown / invalid IANA zone so the
    endpoint can reject a bad preference instead of silently mis-rendering time.
    """
    name = _normalize_text(tz_name, DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:  # unknown key / bad name
        raise LocalizationError(f"unknown time zone {name!r}") from exc


def _parse_utc(value: Any) -> datetime:
    """Coerce an ISO string / datetime into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise LocalizationError(f"invalid timestamp {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local_time(iso_utc: Any, tz_name: Optional[str] = None) -> dict[str, Any]:
    """Render a stored UTC instant in the viewer's local zone."""
    dt = _parse_utc(iso_utc)
    zone = resolve_zone(tz_name)
    local = dt.astimezone(zone)
    return {
        "utc": dt.isoformat().replace("+00:00", "Z"),
        "local_iso": local.isoformat(),
        "local_display": local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "timezone": str(zone),
        "utc_offset": local.strftime("%z"),
        "is_dst": bool(local.dst()),
    }


def format_wind_direction(degrees: Optional[float]) -> dict[str, Any]:
    """Turn a wind bearing into degrees + a 16-point compass label."""
    if degrees is None:
        return {"degrees": None, "compass": None, "compass_full": None}
    bearing = float(degrees) % 360.0
    index = int((bearing + 11.25) % 360.0 // 22.5)
    return {
        "degrees": round(bearing, 1),
        "compass": _COMPASS_16[index],
        "compass_full": _COMPASS_FULL[index],
    }


def _to_dms(value: float, positive: str, negative: str) -> str:
    """Format one signed axis as ``D M' S.s" H`` (degrees/minutes/seconds)."""
    hemisphere = positive if value >= 0 else negative
    magnitude = abs(value)
    degrees = int(magnitude)
    minutes_full = (magnitude - degrees) * 60.0
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60.0, 3)
    if seconds >= 60.0:
        seconds -= 60.0
        minutes += 1
    if minutes >= 60:
        minutes -= 60
        degrees += 1
    return f"{degrees}\u00b0{minutes:02d}'{seconds:04.1f}\" {hemisphere}"


def format_coordinates(
    latitude: Optional[float],
    longitude: Optional[float],
    coord_format: Optional[str] = None,
) -> dict[str, Any]:
    """Format a WGS-84 point in the operator's chosen display format.

    Both the decimal and DMS renderings are always returned so a UI toggle can
    switch without another round-trip; ``display`` carries the requested format.
    """
    if latitude is None or longitude is None:
        raise LocalizationError("latitude and longitude are both required")
    lat = float(latitude)
    lon = float(longitude)
    if not -90.0 <= lat <= 90.0:
        raise LocalizationError(f"latitude out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise LocalizationError(f"longitude out of range: {lon}")
    fmt = _normalize_text(coord_format, DEFAULT_COORDINATE_FORMAT).lower()
    if fmt not in COORDINATE_FORMATS:
        raise LocalizationError(f"unknown coordinate format {fmt!r}")
    decimal = {
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "string": f"{lat:.6f}, {lon:.6f}",
    }
    dms = {
        "latitude": _to_dms(lat, "N", "S"),
        "longitude": _to_dms(lon, "E", "W"),
        "string": f"{_to_dms(lat, 'N', 'S')} {_to_dms(lon, 'E', 'W')}",
    }
    return {
        "format": fmt,
        "decimal": decimal,
        "dms": dms,
        "display": decimal["string"] if fmt == "decimal" else dms["string"],
    }


def format_metric(value: Optional[float], unit: str) -> dict[str, Any]:
    """Describe one metric measurement (value rounded + explicit unit label)."""
    if value is None:
        return {"value": None, "unit": unit, "display": "\u2014"}
    rounded = round(float(value), 3)
    return {"value": rounded, "unit": unit, "display": f"{rounded} {unit}"}


def standardize(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the display standardization described by ``payload``.

    Each block is produced only when the caller supplied the inputs it needs,
    so one request can localize a clock, format a coordinate, read a wind
    bearing and stamp metric units together. Read-only; nothing is persisted.
    """
    tz_name = payload.get("timezone")
    result: dict[str, Any] = {
        "panel": "display_standardization",
        "units": UNITS,
        "requested_timezone": _normalize_text(tz_name, DEFAULT_TIMEZONE),
        "coordinate_format": _normalize_text(
            payload.get("coordinate_format"), DEFAULT_COORDINATE_FORMAT
        ).lower(),
        "attribution": LOCALIZATION_ATTRIBUTION,
        "persistence": LOCALIZATION_PERSISTENCE,
    }

    if payload.get("time") is not None:
        result["time"] = to_local_time(payload["time"], tz_name)
    if payload.get("latitude") is not None or payload.get("longitude") is not None:
        result["coordinate"] = format_coordinates(
            payload.get("latitude"),
            payload.get("longitude"),
            payload.get("coordinate_format"),
        )
    if payload.get("wind_direction_deg") is not None:
        result["wind"] = format_wind_direction(payload["wind_direction_deg"])

    metric_map = (
        ("distance_km", "km"),
        ("area_ha", "ha"),
        ("speed_kmh", "km/h"),
    )
    measures = {
        key: format_metric(payload.get(key), unit)
        for key, unit in metric_map
        if payload.get(key) is not None
    }
    if measures:
        result["measures"] = measures
    return result


__all__ = [
    "COORDINATE_FORMATS",
    "DEFAULT_COORDINATE_FORMAT",
    "DEFAULT_TIMEZONE",
    "LOCALIZATION_ATTRIBUTION",
    "LOCALIZATION_PERSISTENCE",
    "SUPPORTED_TIMEZONES",
    "UNITS",
    "LocalizationError",
    "format_coordinates",
    "format_metric",
    "format_wind_direction",
    "resolve_zone",
    "standardize",
    "to_local_time",
]
