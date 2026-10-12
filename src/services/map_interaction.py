"""Map interaction toolkit (EM-080, Epic E8).

An operator assessing a fire "in its surroundings" needs three things on the
one map they already stare at (EM-080 acceptance: switch between street /
satellite / terrain basemaps; search a place name *and* a raw coordinate; get
a distance/area measurement tool). None of that existed: the operator map had a
single hard-coded OpenStreetMap tile layer, no search and no measurement.

This module is the deterministic, read-only backing for those three affordances
so the client stays thin and the maths is unit-testable in one place:

* a **basemap catalogue** (street / satellite / terrain) - tile URLs +
  attribution + zoom ceiling, so switching is a data lookup, not string
  literals sprinkled through the view;
* a **place search** over a small, curated pilot-region gazetteer plus a
  **coordinate parser**, so "yer adı ve koordinat araması" both resolve without
  calling any external geocoder (the demo runs offline and must stay
  deterministic - a network reverse-geocode would neither);
* **geodesic measurement** (great-circle distance along a polyline and
  spherical polygon area), so the ruler is real maths on WGS-84, not a flat
  equirectangular approximation.

Nothing is stored - the gazetteer ships with the code, coordinates are typed by
the operator, and measurements are ephemeral - so ``persistence`` is ``none``.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Optional

from src.services.localization import format_coordinates

# Mean Earth radius (WGS-84 authalic-ish) in km and m; the same constant keeps
# distance and area mutually consistent.
_EARTH_RADIUS_KM = 6371.0088
_EARTH_RADIUS_M = _EARTH_RADIUS_KM * 1000.0

# The basemaps the operator toggles between. Tiles are the public XYZ endpoints
# used by the demo; attribution strings must stay visible per each provider's
# licence, so they travel with the catalogue rather than living in the view.
BASEMAPS: tuple[dict[str, Any], ...] = (
    {
        "key": "street",
        "label": "Sokak",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": (
            '&copy; <a href="https://www.openstreetmap.org/copyright">'
            "OpenStreetMap</a> contributors"
        ),
        "max_zoom": 19,
    },
    {
        "key": "satellite",
        "label": "Uydu",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        "attribution": "Tiles &copy; Esri World Imagery contributors",
        "max_zoom": 19,
    },
    {
        "key": "terrain",
        "label": "Arazi",
        "url": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        "attribution": (
            "Map data &copy; OpenTopoMap (CC-BY-SA), "
            "&copy; OpenStreetMap contributors, SRTM"
        ),
        "max_zoom": 17,
    },
)
BASEMAP_KEYS: tuple[str, ...] = tuple(b["key"] for b in BASEMAPS)
DEFAULT_BASEMAP = "street"

# A curated gazetteer of Aegean settlements inside the pilot bounding box
# (lat 36.0-39.5, lon 26.0-30.0). Deliberately small and deterministic: a demo
# offline build cannot (and must not) reach a live geocoder, and inventing a
# "real" gazetteer would overclaim coverage. Country is an authoritative label,
# not the EM-066 border-longitude heuristic, so the two features stay honest.
GAZETTEER: tuple[dict[str, Any], ...] = (
    {
        "name": "Bodrum",
        "country": "TR",
        "kind": "city",
        "latitude": 37.0344,
        "longitude": 27.4294,
    },
    {
        "name": "Marmaris",
        "country": "TR",
        "kind": "city",
        "latitude": 36.8557,
        "longitude": 28.2742,
    },
    {
        "name": "Fethiye",
        "country": "TR",
        "kind": "city",
        "latitude": 36.6198,
        "longitude": 29.1178,
    },
    {
        "name": "Datça",
        "country": "TR",
        "kind": "town",
        "latitude": 36.7397,
        "longitude": 27.6902,
    },
    {
        "name": "Kuşadası",
        "country": "TR",
        "kind": "city",
        "latitude": 37.8595,
        "longitude": 27.2594,
    },
    {
        "name": "Söke",
        "country": "TR",
        "kind": "town",
        "latitude": 37.7517,
        "longitude": 27.0794,
    },
    {
        "name": "Milas",
        "country": "TR",
        "kind": "town",
        "latitude": 37.3206,
        "longitude": 27.7847,
    },
    {
        "name": "Rodos",
        "country": "GR",
        "kind": "city",
        "latitude": 36.4416,
        "longitude": 28.1817,
    },
    {
        "name": "İstanköy",
        "country": "GR",
        "kind": "town",
        "latitude": 36.8900,
        "longitude": 27.2600,
    },
    {
        "name": "Simi",
        "country": "GR",
        "kind": "town",
        "latitude": 36.5856,
        "longitude": 28.1016,
    },
    {
        "name": "Kalymnos",
        "country": "GR",
        "kind": "town",
        "latitude": 36.9367,
        "longitude": 26.9400,
    },
    {
        "name": "Midilli",
        "country": "GR",
        "kind": "town",
        "latitude": 39.1064,
        "longitude": 26.5542,
    },
)

# Search / measurement limits so a stray request cannot fan out unbounded.
DEFAULT_SEARCH_MAX_RESULTS = 8
MAX_SEARCH_RESULTS = 25
MIN_DISTANCE_POINTS = 2
MIN_AREA_POINTS = 3
DEFAULT_MEASURE_MAX_POINTS = 100
MAX_MEASURE_POINTS_CAP = 500

MAP_INTERACTION_ATTRIBUTION = (
    "EM-080: sokak/uydu/arazi altlıkları arasında geçiş; yer adı ve koordinat "
    "araması; mesafe/alan ölçüm aracı. Deterministik ve çevrimdışı: gazete "
    "kodla gelir, ölçüm WGS-84 üzerinde gerçek jeodezik matematik."
)
MAP_INTERACTION_PERSISTENCE = "none"

# "lat, lon" in decimal degrees, tolerating a trailing degree sign / spaces and
# either comma or whitespace separation; captures signed decimals only.
_COORD_RE = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?)\s*°?\s*[,;\s]\s*([-+]?\d+(?:\.\d+)?)\s*°?\s*$"
)


class MapInteractionError(ValueError):
    """Raised for an invalid basemap, unparseable query or bad measurement."""


def _normalize_text(value: Optional[str]) -> str:
    """Lowercase + strip diacritics so a name search is accent-insensitive.

    Turkish needs one special case: the dotless ``ı`` (U+0131) is a distinct
    letter with no NFKD decomposition, so it would never fold to ``i`` on its
    own - map it explicitly before the generic accent folding (``İ``/``ğ``/``ş``
    already decompose to their base letters via NFKD).
    """
    lowered = (value or "").strip().lower().replace("\u0131", "i")
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def basemap_catalog() -> list[dict[str, Any]]:
    """The three basemaps as a defensive copy for the UI to iterate."""
    return [dict(b) for b in BASEMAPS]


def default_basemap(settings: Any = None) -> str:
    """The configured default basemap key, falling back to ``street``.

    An unknown configured value is rejected rather than silently served, so a
    typo in the environment surfaces instead of leaving the map on a blank tile.
    """
    key = DEFAULT_BASEMAP
    if settings is not None:
        key = getattr(settings, "MAP_DEFAULT_BASEMAP", DEFAULT_BASEMAP)
    if key not in BASEMAP_KEYS:
        raise MapInteractionError(f"bilinmeyen altlık: {key!r}")
    return key


def parse_coordinate(text: Optional[str]) -> dict[str, Any]:
    """Parse a ``"lat, lon"`` (decimal degrees) query into a validated point.

    Raises :class:`MapInteractionError` for anything that is not a pair of
    in-range signed decimals so a half-typed coordinate is never mis-centred.
    """
    raw = (text or "").strip()
    match = _COORD_RE.match(raw)
    if not match:
        raise MapInteractionError(f"koordinat çözülemedi: {raw!r}")
    lat = float(match.group(1))
    lon = float(match.group(2))
    if not -90.0 <= lat <= 90.0:
        raise MapInteractionError(f"enlem aralık dışında: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise MapInteractionError(f"boylam aralık dışında: {lon}")
    return {"latitude": lat, "longitude": lon}


def _place_hit(entry: dict[str, Any], coord_format: Optional[str]) -> dict[str, Any]:
    """Shape one gazetteer row (with its formatted coordinate) as a result."""
    formatted = format_coordinates(entry["latitude"], entry["longitude"], coord_format)
    return {
        "name": entry["name"],
        "country": entry["country"],
        "kind": entry["kind"],
        "latitude": entry["latitude"],
        "longitude": entry["longitude"],
        "match": "place",
        "display": formatted["display"],
        "coordinate": formatted,
    }


def _coordinate_hit(
    point: dict[str, Any], coord_format: Optional[str]
) -> dict[str, Any]:
    """Shape a parsed raw coordinate as a result."""
    formatted = format_coordinates(point["latitude"], point["longitude"], coord_format)
    return {
        "name": formatted["display"],
        "country": None,
        "kind": "coordinate",
        "latitude": point["latitude"],
        "longitude": point["longitude"],
        "match": "coordinate",
        "display": formatted["display"],
        "coordinate": formatted,
    }


def search_places(query: Optional[str], settings: Any = None) -> dict[str, Any]:
    """Resolve a place-name *or* coordinate query against the gazetteer.

    A raw coordinate always produces a first ``coordinate`` hit; place names
    match accent-insensitively on a substring. An exact-name match ranks ahead
    of a substring one. Results are capped by ``MAP_SEARCH_MAX_RESULTS``; a
    blank query yields an empty list rather than dumping the whole gazetteer.
    """
    text = (query or "").strip()
    max_results = DEFAULT_SEARCH_MAX_RESULTS
    coord_format: Optional[str] = None
    if settings is not None:
        max_results = getattr(
            settings, "MAP_SEARCH_MAX_RESULTS", DEFAULT_SEARCH_MAX_RESULTS
        )
        coord_format = getattr(settings, "DISPLAY_COORDINATE_FORMAT", None)
    max_results = max(1, min(int(max_results), MAX_SEARCH_RESULTS))

    if not text:
        return {
            "query": text,
            "results": [],
            "max_results": max_results,
            "attribution": MAP_INTERACTION_ATTRIBUTION,
            "persistence": MAP_INTERACTION_PERSISTENCE,
        }

    results: list[dict[str, Any]] = []
    try:
        results.append(_coordinate_hit(parse_coordinate(text), coord_format))
    except MapInteractionError:
        pass

    needle = _normalize_text(text)
    if needle:
        exact = [e for e in GAZETTEER if _normalize_text(e["name"]) == needle]
        partial = [
            e
            for e in GAZETTEER
            if needle in _normalize_text(e["name"]) and e not in exact
        ]
        for entry in exact + partial:
            results.append(_place_hit(entry, coord_format))

    return {
        "query": text,
        "results": results[:max_results],
        "max_results": max_results,
        "attribution": MAP_INTERACTION_ATTRIBUTION,
        "persistence": MAP_INTERACTION_PERSISTENCE,
    }


def _max_points(settings: Any = None) -> int:
    cap = DEFAULT_MEASURE_MAX_POINTS
    if settings is not None:
        cap = getattr(settings, "MAP_MEASURE_MAX_POINTS", DEFAULT_MEASURE_MAX_POINTS)
    return max(MIN_AREA_POINTS, min(int(cap), MAX_MEASURE_POINTS_CAP))


def _validated_points(
    points: Any, minimum: int, max_points: int
) -> list[tuple[float, float]]:
    """Coerce a measurement input to ``(lat, lon)`` pairs and sanity-check it."""
    if not isinstance(points, (list, tuple)):
        raise MapInteractionError("points bir [enlem, boylam] listesi olmalı")
    coords: list[tuple[float, float]] = []
    for item in points:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise MapInteractionError(f"geçersiz nokta: {item!r}")
        lat = float(item[0])
        lon = float(item[1])
        if not -90.0 <= lat <= 90.0:
            raise MapInteractionError(f"enlem aralık dışında: {lat}")
        if not -180.0 <= lon <= 180.0:
            raise MapInteractionError(f"boylam aralık dışında: {lon}")
        coords.append((lat, lon))
    if len(coords) < minimum:
        raise MapInteractionError(f"en az {minimum} nokta gerekli")
    if len(coords) > max_points:
        raise MapInteractionError(f"en fazla {max_points} nokta kabul edilir")
    return coords


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two ``(lat, lon)`` points, in km."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return _EARTH_RADIUS_KM * 2.0 * math.asin(min(1.0, math.sqrt(h)))


def measure_distance(points: Any, settings: Any = None) -> dict[str, Any]:
    """Total great-circle distance (km) along an ordered polyline of points."""
    max_points = _max_points(settings)
    coords = _validated_points(points, MIN_DISTANCE_POINTS, max_points)
    segments: list[dict[str, Any]] = [
        {
            "from": list(coords[i]),
            "to": list(coords[i + 1]),
            "distance_km": round(_haversine_km(coords[i], coords[i + 1]), 3),
        }
        for i in range(len(coords) - 1)
    ]
    # Sum the per-segment legs once: recomputing _haversine_km here would walk
    # the polyline twice for the same answer.
    total_km = sum(seg["distance_km"] for seg in segments)
    return {
        "mode": "distance",
        "points": [list(c) for c in coords],
        "segments": segments,
        "distance_km": round(total_km, 3),
        "attribution": MAP_INTERACTION_ATTRIBUTION,
        "persistence": MAP_INTERACTION_PERSISTENCE,
    }


def _spherical_area_m2(coords: list[tuple[float, float]]) -> float:
    """Absolute geodesic area (m^2) of a lat/lon polygon (spherical excess)."""
    total = 0.0
    n = len(coords)
    for i in range(n):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[(i + 1) % n]
        dlon = math.radians(lon2 - lon1)
        total += dlon * (
            2.0 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
        )
    return abs(total) * _EARTH_RADIUS_M * _EARTH_RADIUS_M / 2.0


def measure_area(points: Any, settings: Any = None) -> dict[str, Any]:
    """Geodesic area of a lat/lon polygon, in hectares and km^2.

    The ring is treated as closed (last vertex joins the first) whether or not
    the caller repeats the first coordinate, so the operator just clicks corners.
    """
    max_points = _max_points(settings)
    coords = _validated_points(points, MIN_AREA_POINTS, max_points)
    ring = list(coords)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    area_m2 = _spherical_area_m2(ring)
    return {
        "mode": "area",
        "points": [list(c) for c in coords],
        "area_m2": round(area_m2, 1),
        "area_ha": round(area_m2 / 10000.0, 3),
        "area_km2": round(area_m2 / 1_000_000.0, 4),
        "attribution": MAP_INTERACTION_ATTRIBUTION,
        "persistence": MAP_INTERACTION_PERSISTENCE,
    }


def map_interaction_config(settings: Any = None) -> dict[str, Any]:
    """Everything the operator map needs to render the three EM-080 tools."""
    try:
        resolved_default = default_basemap(settings)
    except MapInteractionError:
        resolved_default = DEFAULT_BASEMAP
    max_points = _max_points(settings)
    max_results = DEFAULT_SEARCH_MAX_RESULTS
    if settings is not None:
        max_results = getattr(
            settings, "MAP_SEARCH_MAX_RESULTS", DEFAULT_SEARCH_MAX_RESULTS
        )
    return {
        "panel": "map_interaction",
        "basemaps": basemap_catalog(),
        "default_basemap": resolved_default,
        "gazetteer_size": len(GAZETTEER),
        "search_max_results": max(1, min(int(max_results), MAX_SEARCH_RESULTS)),
        "measure": {
            "min_distance_points": MIN_DISTANCE_POINTS,
            "min_area_points": MIN_AREA_POINTS,
            "max_points": max_points,
        },
        "attribution": MAP_INTERACTION_ATTRIBUTION,
        "persistence": MAP_INTERACTION_PERSISTENCE,
    }


__all__ = [
    "BASEMAPS",
    "BASEMAP_KEYS",
    "DEFAULT_BASEMAP",
    "DEFAULT_MEASURE_MAX_POINTS",
    "DEFAULT_SEARCH_MAX_RESULTS",
    "GAZETTEER",
    "MAP_INTERACTION_ATTRIBUTION",
    "MAP_INTERACTION_PERSISTENCE",
    "MAX_MEASURE_POINTS_CAP",
    "MAX_SEARCH_RESULTS",
    "MapInteractionError",
    "basemap_catalog",
    "default_basemap",
    "map_interaction_config",
    "measure_area",
    "measure_distance",
    "parse_coordinate",
    "search_places",
]
