"""EM-021 land/sea mask and natural barriers for the spread engine.

Water bodies and non-burnable surfaces are excluded from the spread
calculation: horizon polygons are clipped at the shoreline so they never
spill into the sea, a lake or a wide river. Partial obstacles such as roads
and small streams are modelled with a slowdown coefficient applied to every
spread ray that crosses them.

Barrier semantics are driven by ``slowdown_factor``:

* ``0.0``  full barrier - rays are clipped at the first boundary crossing
  (fire cannot pass); polygons never extend beyond the water edge.
* ``0 < f < 1``  partial obstacle - the reach along crossing rays is
  multiplied by ``f`` (fire slows down but may cross).

All geometry works in the local metric ENU frame (metres east/north) the
spread engine already projects horizon polygons into, so masking composes
with both the EM-015 ellipse and the EM-016 fuel-transition rings.
"""
from math import cos, hypot, radians
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import NaturalBarrier
from src.services.layer_cache import cached_value, layer_cache, perf_enabled

METERS_PER_DEGREE_LAT = 111320.0  # WGS-84 mean Earth meridian circumference

# Registered barrier types and their expected WKT geometry.
BARRIER_GEOMETRY = {
    "sea": "polygon",
    "lake": "polygon",
    "wide_river": "polygon",
    "non_burnable": "polygon",
    "road": "line",
    "river": "line",
}

# Default slowdown coefficient per barrier type (0.0 = fire cannot cross).
DEFAULT_SLOWDOWN = {
    "sea": 0.0,
    "lake": 0.0,
    "wide_river": 0.0,
    "non_burnable": 0.0,
    "road": 0.6,
    "river": 0.7,
}

_EPS = 1e-9

# EM-022: cache key prefix for the decoded active-barrier list.
BARRIER_CACHE_KEY = ("barriers",)


class BarrierError(RuntimeError):
    """Raised when a barrier definition or geometry cannot be used."""


def parse_polygon_ring(wkt: str | None) -> list[list[float]]:
    """Parse ``POLYGON((lon lat, ...))`` into a [lon, lat] ring."""
    text = (wkt or "").strip()
    if not text.upper().startswith("POLYGON((") or not text.endswith("))"):
        raise BarrierError("expected a POLYGON((lon lat, ...)) geometry")
    ring: list[list[float]] = []
    for pair in text[len("POLYGON((") : -2].split(","):
        parts = pair.strip().split()
        if len(parts) != 2:
            raise BarrierError(f"malformed polygon coordinate pair: '{pair}'")
        try:
            ring.append([float(parts[0]), float(parts[1])])
        except ValueError as exc:
            raise BarrierError(f"invalid coordinate '{pair}': {exc}") from exc
    if len(ring) < 4:
        raise BarrierError("polygon ring needs at least 4 points (closed)")
    return ring


def parse_line_string(wkt: str | None) -> list[list[float]]:
    """Parse ``LINESTRING(lon lat, ...)`` into a [lon, lat] point list."""
    text = (wkt or "").strip()
    if not text.upper().startswith("LINESTRING(") or not text.endswith(")"):
        raise BarrierError("expected a LINESTRING(lon lat, ...) geometry")
    line: list[list[float]] = []
    for pair in text[len("LINESTRING(") : -1].split(","):
        parts = pair.strip().split()
        if len(parts) != 2:
            raise BarrierError(f"malformed line coordinate pair: '{pair}'")
        try:
            line.append([float(parts[0]), float(parts[1])])
        except ValueError as exc:
            raise BarrierError(f"invalid coordinate '{pair}': {exc}") from exc
    if len(line) < 2:
        raise BarrierError("linestring needs at least 2 points")
    return line


def _to_local(
    geo_points: list[list[float]], lat0: float, lon0: float
) -> list[list[float]]:
    """Convert [lon, lat] points to local ENU metres around (lat0, lon0)."""
    meters_per_lon = METERS_PER_DEGREE_LAT * max(cos(radians(lat0)), 0.1)
    return [
        [
            (lon - lon0) * meters_per_lon,
            (lat - lat0) * METERS_PER_DEGREE_LAT,
        ]
        for lon, lat in geo_points
    ]


def point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test on a local-metric closed ring."""
    x, y = point
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _cross(ux: float, uy: float, vx: float, vy: float) -> float:
    return ux * vy - uy * vx


def _first_intersection_t(
    target: list[float], segments: list[tuple[list[float], list[float]]]
) -> float | None:
    """Smallest t in (0, 1] where segment O->target crosses any barrier edge.

    Returns the fractional distance along O->target, or None when the ray
    does not hit any segment.
    """
    dx, dy = target
    best: float | None = None
    for (ax, ay), (bx, by) in segments:
        ex, ey = bx - ax, by - ay
        denom = _cross(dx, dy, ex, ey)
        if abs(denom) < _EPS:
            continue  # parallel / collinear
        t = _cross(ax, ay, ex, ey) / denom
        u = _cross(ax, ay, dx, dy) / denom
        if -_EPS < t <= 1.0 + _EPS and -_EPS <= u <= 1.0 + _EPS:
            t = min(max(t, 0.0), 1.0)
            if best is None or t < best:
                best = t
    return best


def _ring_edges(ring: list[list[float]]) -> list[tuple[list[float], list[float]]]:
    return [(ring[i], ring[i + 1]) for i in range(len(ring) - 1)]


def _line_edges(line: list[list[float]]) -> list[tuple[list[float], list[float]]]:
    return [(line[i], line[i + 1]) for i in range(len(line) - 1)]


def load_active_barriers(
    session: Session | None, settings: Any = None
) -> list[dict[str, Any]]:
    """Decode active barrier rows into local-frame-free geographic dicts.

    With EM-022 (``settings`` given and SPREAD_PERF_ENABLED) the decoded
    list is served from the layer cache; register/delete invalidate it, so
    operators still see barrier changes immediately. Treat the returned
    list as read-only: cached runs share one instance.
    """
    if session is None:
        return []
    db_session: Session = session
    if settings is None or not perf_enabled(settings):
        return _load_active_barriers(db_session)
    return cached_value(
        db_session,
        BARRIER_CACHE_KEY,
        lambda: _load_active_barriers(db_session),
        settings,
    )


def _load_active_barriers(session: Session) -> list[dict[str, Any]]:
    """Uncached barrier decode (the loader behind the EM-022 cache)."""
    barriers = []
    rows = session.scalars(
        select(NaturalBarrier).where(NaturalBarrier.is_active.is_(True))
    ).all()
    for row in rows:
        geometry_kind = BARRIER_GEOMETRY.get(str(row.barrier_type))
        try:
            if geometry_kind == "polygon":
                geo = parse_polygon_ring(str(row.geometry_wkt))
            elif geometry_kind == "line":
                geo = parse_line_string(str(row.geometry_wkt))
            else:
                continue  # unknown type stored earlier: skip, never crash
        except BarrierError:
            continue
        barriers.append(
            {
                "barrier_key": str(row.barrier_key),
                "barrier_type": str(row.barrier_type),
                "geometry_kind": geometry_kind,
                "geo_points": geo,
                "slowdown_factor": float(row.slowdown_factor),
            }
        )
    return barriers


def mask_local_ring(
    ignition_lat: float,
    ignition_lon: float,
    points: list[list[float]],
    barriers: list[dict[str, Any]],
) -> list[list[float]]:
    """Clip/slow a local-metric horizon ring so it respects EM-021 barriers.

    ``points`` is the closed ring produced by the spread engine (metres
    east/north relative to the ignition point, which sits at the origin).
    Full barriers truncate each ray at the first boundary crossing; partial
    obstacles multiply crossing rays by their slowdown coefficient.
    """
    if not barriers or not points:
        return points
    prepared: list[dict[str, Any]] = []
    for barrier in barriers:
        local = _to_local(barrier["geo_points"], ignition_lat, ignition_lon)
        if barrier["geometry_kind"] == "polygon":
            if local[0] != local[-1]:
                local.append(list(local[0]))
            edges = _ring_edges(local)
        else:
            edges = _line_edges(local)
        prepared.append(
            {
                "edges": edges,
                "ring": local if barrier["geometry_kind"] == "polygon" else None,
                "factor": barrier["slowdown_factor"],
            }
        )
    full = [b for b in prepared if b["factor"] <= 0.0]
    partial = [b for b in prepared if 0.0 < b["factor"] < 1.0]

    # Ignition point inside a full barrier is a data error: nothing can burn.
    for barrier in full:
        if barrier["ring"] and point_in_ring([0.0, 0.0], barrier["ring"]):
            return [[0.0, 0.0] for _ in points]

    masked: list[list[float]] = []
    for point in points:
        east, north = point
        radius = hypot(east, north)
        if radius <= 0.0:
            masked.append([0.0, 0.0])
            continue
        ux, uy = east / radius, north / radius
        for barrier in full:
            # First boundary crossing truncates the ray: this both clips a
            # vertex standing in the water to the shoreline and stops rays
            # that would otherwise cross a lake/strait to burn beyond it.
            t = _first_intersection_t([ux * radius, uy * radius], barrier["edges"])
            if t is not None:
                radius *= t
        if radius <= 0.0:
            masked.append([0.0, 0.0])
            continue
        for barrier in partial:
            t = _first_intersection_t([ux * radius, uy * radius], barrier["edges"])
            if t is not None:
                radius *= barrier["factor"]
        masked.append([round(ux * radius, 2), round(uy * radius, 2)])
    return masked


def apply_barriers(
    session: Session | None,
    settings: Any,
    ignition_lat: float,
    ignition_lon: float,
    points: list[list[float]],
) -> list[list[float]]:
    """Settings-gated convenience wrapper used by the spread engine."""
    if not bool(getattr(settings, "SPREAD_BARRIERS_ENABLED", True)):
        return points
    barriers = load_active_barriers(session)
    return mask_local_ring(ignition_lat, ignition_lon, points, barriers)


def register_barrier(session: Session, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist one EM-021 natural barrier."""
    barrier_type = str(fields.get("barrier_type") or "")
    if barrier_type not in BARRIER_GEOMETRY:
        raise BarrierError(
            f"unknown barrier_type '{barrier_type}'; "
            f"expected one of {sorted(BARRIER_GEOMETRY)}"
        )
    name = str(fields.get("name") or "").strip()
    if not name:
        raise BarrierError("name is required")
    wkt = str(fields.get("geometry_wkt") or "")
    if BARRIER_GEOMETRY[barrier_type] == "polygon":
        parse_polygon_ring(wkt)
    else:
        parse_line_string(wkt)
    factor = fields.get("slowdown_factor")
    factor = DEFAULT_SLOWDOWN[barrier_type] if factor is None else float(factor)
    if not 0.0 <= factor < 1.0:
        raise BarrierError("slowdown_factor must be in [0, 1): 0 blocks, 0.6 slows")
    barrier_key = str(fields.get("barrier_key") or f"BAR-{uuid4().hex[:10]}")
    existing = session.scalar(
        select(NaturalBarrier).where(NaturalBarrier.barrier_key == barrier_key)
    )
    if existing is not None:
        raise BarrierError(f"barrier {barrier_key} already exists")
    row = NaturalBarrier(
        barrier_key=barrier_key,
        name=name,
        barrier_type=barrier_type,
        geometry_wkt=wkt,
        slowdown_factor=factor,
        is_active=bool(fields.get("is_active", True)),
        source=str(fields.get("source") or "operator"),
        notes=fields.get("notes"),
    )
    session.add(row)
    session.commit()
    layer_cache().invalidate(BARRIER_CACHE_KEY)
    return row.as_dict


def list_barriers(session: Session) -> list[dict[str, Any]]:
    """All registered barriers, newest first."""
    rows = session.scalars(
        select(NaturalBarrier).order_by(NaturalBarrier.id.desc())
    ).all()
    return [row.as_dict for row in rows]


def delete_barrier(session: Session, barrier_key: str) -> bool:
    """Remove one barrier; returns whether it existed."""
    row = session.scalar(
        select(NaturalBarrier).where(NaturalBarrier.barrier_key == barrier_key)
    )
    if row is None:
        return False
    session.delete(row)
    session.commit()
    layer_cache().invalidate(BARRIER_CACHE_KEY)
    return True
