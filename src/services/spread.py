"""Rothermel-based fundamental fire spread engine (EM-015).

Computes the head-fire rate of spread with Rothermel's (1972) surface spread
model (Albini 1976 adjustments), converts it into elliptical risk-zone
polygons for the 30/60/120 minute horizons, and persists each horizon as a
FireForecast row.

The equations and the 13 USFS standard fuel-model parameter records are
ported from the public-domain USDA implementation lineage:
 - BehavePlus / behave_plus (RMRS Missoula Fire Sciences Laboratory),
   src/behave/fuelModels.cpp and surfaceFuelbedIntermediates.cpp, and
 - emxsys/behave Rothermel.js (MIT), which mirrors the same equations.
Internal arithmetic stays in Rothermel's native imperial units; SI values are
used at the API boundary. The engine is fully deterministic: identical
inputs always produce identical rates, directions, and polygons.

References:
 - Rothermel, R.C., 1972. A mathematical model for predicting fire spread in
   wildland fuels. Res. Pap. INT-115, USDA Forest Service.
 - Albini, F.A., 1976. Estimating wildfire behavior and effects. Gen. Tech.
   Rep. INT-30, USDA Forest Service.
 - Anderson, H.I. et al., 1982. A guide for fuel model management.
   Gen. Tech. Rep. INT-193 (13 standard fuel models).
 - Rothermel, R.C. et al., 1986. Modeling moisture content of fine dead
   wildland fuels. Res. Pap. INT-359 (Van Wagner equilibrium moisture).
"""
from dataclasses import dataclass
from datetime import timedelta
import functools
import json
import math
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.land_cover import LandCoverDataPoint
from src.models.spatial import FireForecast
from src.models.topography import TopographyDataPoint
from src.models.weather import WeatherDataPoint
from src.services.barriers import load_active_barriers, mask_local_ring
from src.services.fuel_moisture import (
    MODEL_NAME as FUEL_MOISTURE_MODEL_NAME,
)
from src.services.fuel_moisture import (
    FuelMoistureError,
    dead_fuel_moisture,
    equilibrium_moisture_content,
)
from src.services.land_cover import LandCoverFuelService
from src.services.layer_cache import (
    RowView,
    cached_nearest_value,
    perf_enabled,
)
from src.utils.timeutils import to_utc_iso, utc_now

# Unit conversion factors (exact definitions).
FT_PER_M = 1.0 / 0.3048
M_PER_FT = 0.3048
MPH_PER_KMH = 1.0 / 1.609344
FT_MIN_PER_MPH = 88.0
MS_TO_KMH = 3.6
METERS_PER_DEGREE_LAT = 111320.0  # WGS-84 mean Earth meridian circumference

# Shared fuel-bed constants from the USFS standard fuel-model records.
PARTICLE_DENSITY_LB_FT3 = 32.0  # oven-dry particle density for all classes
TOTAL_MINERAL_CONTENT = 0.0555  # lb minerals / lb wood
EFFECTIVE_MINERAL_CONTENT = 0.010  # (lb minerals - lb silica) / lb wood
HEAT_OF_COMBUSTION_BTU_LB = 8000.0
# SAVR for the dead 10-hour / 100-hour classes (behave_plus convention).
SAVR_DEAD_10HOUR = 109.0
SAVR_DEAD_100HOUR = 30.0

DEFAULT_FUEL_MODEL = 4  # chaparral/maquis: dominant Med. landscape class

# USFS standard 13 fuel models (Cheney et al. / Anderson et al.), values in
# Rothermel native units, ported from behave_plus fuelModels.cpp
# (public domain): (name, depth_ft, moisture_of_extinction_fraction,
#  load_1h, load_10h, load_100h, load_live_herb, load_live_wood [lb/ft2],
#  savr_1h, savr_live_herb, savr_live_wood [ft2/ft3]).
FUEL_MODEL_RECORDS: dict[
    int,
    tuple[str, float, float, float, float, float, float, float, float, float, float],
] = {
    1: ("FM1_ShortGrass", 1.0, 0.12, 0.034, 0.0, 0.0, 0.0, 0.0, 3500.0, 1500.0, 1500.0),
    2: (
        "FM2_TimberGrassUnderstory",
        1.0,
        0.15,
        0.092,
        0.046,
        0.023,
        0.023,
        0.0,
        3000.0,
        1500.0,
        1500.0,
    ),
    3: ("FM3_TallGrass", 2.5, 0.25, 0.138, 0.0, 0.0, 0.0, 0.0, 1500.0, 1500.0, 1500.0),
    4: (
        "FM4_Chaparral",
        6.0,
        0.20,
        0.230,
        0.184,
        0.092,
        0.0,
        0.230,
        2000.0,
        1500.0,
        1500.0,
    ),
    5: ("FM5_Brush", 2.0, 0.20, 0.046, 0.023, 0.0, 0.0, 0.092, 2000.0, 1500.0, 1500.0),
    6: (
        "FM6_DormantBrushHardwoodSlash",
        2.5,
        0.25,
        0.069,
        0.115,
        0.092,
        0.0,
        0.0,
        1750.0,
        1500.0,
        1500.0,
    ),
    7: (
        "FM7_SouthernRough",
        2.5,
        0.40,
        0.052,
        0.086,
        0.069,
        0.0,
        0.017,
        1750.0,
        1500.0,
        1500.0,
    ),
    8: (
        "FM8_ShortNeedleLitter",
        0.2,
        0.30,
        0.069,
        0.046,
        0.115,
        0.0,
        0.0,
        2000.0,
        1500.0,
        1500.0,
    ),
    9: (
        "FM9_LongNeedleHardwoodLitter",
        0.2,
        0.25,
        0.134,
        0.019,
        0.007,
        0.0,
        0.0,
        2500.0,
        1500.0,
        1500.0,
    ),
    10: (
        "FM10_TimberLitterUnderstory",
        1.0,
        0.25,
        0.138,
        0.092,
        0.230,
        0.0,
        0.092,
        2000.0,
        1500.0,
        1500.0,
    ),
    11: (
        "FM11_LightLoggingSlash",
        1.0,
        0.15,
        0.069,
        0.207,
        0.253,
        0.0,
        0.0,
        1500.0,
        1500.0,
        1500.0,
    ),
    12: (
        "FM12_MediumLoggingSlash",
        2.3,
        0.20,
        0.184,
        0.644,
        0.759,
        0.0,
        0.0,
        1500.0,
        1500.0,
        1500.0,
    ),
    13: (
        "FM13_HeavyLoggingSlash",
        3.0,
        0.25,
        0.322,
        1.058,
        1.288,
        0.0,
        0.0,
        1500.0,
        1500.0,
        1500.0,
    ),
}

# Project fuel labels (CORINE mapping, config/corine_fuel_map.json) to USFS
# standard model numbers. Unknown labels fall back to DEFAULT_FUEL_MODEL.
PROJECT_FUEL_ALIASES: dict[str, int] = {
    "FM1_Agriculture": 1,
    "FM4_Maquis": 4,
    "FM8_MixedForest": 8,
    "FM10_RedPine": 10,
    "varsayilan": DEFAULT_FUEL_MODEL,
    "bilinmiyor": DEFAULT_FUEL_MODEL,
}


class SpreadError(RuntimeError):
    """Raised when spread inputs are invalid or computation cannot proceed."""


@dataclass(frozen=True)
class FuelBed:
    """Pre-computed Rothermel fuel-bed intermediates for one fuel model."""

    number: int
    name: str
    depth_ft: float
    moisture_of_extinction: float  # fraction
    sigma: float  # characteristic SAV ratio [ft2/ft3]
    beta: float  # packing ratio
    beta_opt: float  # optimum packing ratio
    total_load: float  # lb/ft2
    net_load: float  # lb/ft2 (mineral matter removed)


@dataclass(frozen=True)
class SpreadRates:
    """Rothermel rate-of-spread results in SI units (m/min)."""

    base_m_min: float  # no-wind, no-slope (backing fire) rate
    head_m_min: float  # head fire rate including wind and slope
    wind_factor: float
    slope_factor: float
    reaction_intensity: float  # Btu/ft2/min (diagnostics)
    fuel: FuelBed

    @property
    def spread_multiplier(self) -> float:
        """Combined wind/slope multiplier (1 + phi_w + phi_s)."""
        return 1.0 + self.wind_factor + self.slope_factor


def resolve_fuel_model_number(fuel_model: str | int | None) -> int:
    """Map a project fuel label, numeric id or None to a standard model number."""
    if fuel_model is None or fuel_model == "":
        return DEFAULT_FUEL_MODEL
    if isinstance(fuel_model, int):
        number = fuel_model
    else:
        text = str(fuel_model).strip()
        if text.isdigit():
            number = int(text)
        else:
            for alias, number_value in PROJECT_FUEL_ALIASES.items():
                if text.lower().startswith(alias.lower()):
                    return number_value
            for key, record in FUEL_MODEL_RECORDS.items():
                if text.lower() in (record[0].lower(), f"fm{key}"):
                    return key
            return DEFAULT_FUEL_MODEL
    if number not in FUEL_MODEL_RECORDS:
        raise SpreadError(f"Unsupported fuel model '{fuel_model}'")
    return number


@functools.lru_cache(maxsize=16)
def compute_fuel_bed(model_number: int) -> FuelBed:
    """Compute Rothermel fuel-bed intermediates for one standard fuel model."""
    if model_number not in FUEL_MODEL_RECORDS:
        raise SpreadError(f"Unknown fuel model {model_number}")
    record = FUEL_MODEL_RECORDS[model_number]
    name, depth, mx, w1, w10, w100, wh, wl, sv1, svh, svl = record

    classes = [
        (w1, sv1),
        (w10, SAVR_DEAD_10HOUR),
        (w100, SAVR_DEAD_100HOUR),
        (wh, svh),
        (wl, svl),
    ]
    total_load = sum(w for w, _ in classes)
    if total_load <= 0 or depth <= 0:
        raise SpreadError(f"Fuel model {model_number} has no usable load/depth")

    # Characteristic SAV ratio: surface-area weighted (Rothermel 1972 eq 71-72)
    sw = sum(sv * w for w, sv in classes)
    s2w = sum(sv * sv * w for w, sv in classes)
    sigma = s2w / sw

    bulk_density = total_load / depth
    beta = bulk_density / PARTICLE_DENSITY_LB_FT3
    beta_opt = 3.348 * sigma**-0.8189
    return FuelBed(
        number=model_number,
        name=name,
        depth_ft=depth,
        moisture_of_extinction=mx,
        sigma=sigma,
        beta=beta,
        beta_opt=beta_opt,
        total_load=total_load,
        net_load=total_load * (1.0 - TOTAL_MINERAL_CONTENT),
    )


def midflame_wind_adjustment_factor(depth_ft: float) -> float:
    """Wind adjustment factor from the 10 m wind to mid-flame height.

    Albini & Baughman (1979) / BehavePlus logarithmic wind profile.
    """
    if depth_ft <= 0:
        return 1.0
    waf = 1.83 / math.log((20.0 + 0.36 * depth_ft) / (0.13 * depth_ft))
    return min(max(waf, 0.0), 1.0)


def equilibrium_fuel_moisture(air_temp_c: float, rel_humidity_pct: float) -> float:
    """1-hour dead fuel equilibrium moisture content [%] (Van Wagner curves).

    Thin re-export of :func:`src.services.fuel_moisture.equilibrium_moisture_content`
    kept for API compatibility (EM-015 tests); the full per-class model
    lives in the fuel_moisture module (EM-019).
    """
    return equilibrium_moisture_content(air_temp_c, rel_humidity_pct)


def effective_dead_fuel_moisture(model_number: int, classes: dict[str, float]) -> float:
    """Load-weighted effective moisture of the dead fuel classes [%] (EM-019).

    Weights are the 1-h / 10-h / 100-h dead loads of the standard fuel
    model record, so grass-dominated beds follow the fast (dry) class while
    slash-heavy beds are pulled towards the wetter coarse classes.
    """
    record = FUEL_MODEL_RECORDS[model_number]
    loads = (record[3], record[4], record[5])  # w1, w10, w100 [lb/ft2]
    total = sum(loads)
    if total <= 0:
        return float(classes["moisture_1h_pct"])
    weighted = (
        loads[0] * classes["moisture_1h_pct"]
        + loads[1] * classes["moisture_10h_pct"]
        + loads[2] * classes["moisture_100h_pct"]
    )
    return round(weighted / total, 2)


def spread_rates(
    fuel_model: str | int | None,
    fuel_moisture_pct: float,
    wind_kmh_10m: float,
    slope_deg: float,
) -> SpreadRates:
    """Rothermel head-fire and backing-fire rate of spread (m/min).

    All live and dead fuel classes are evaluated at the single supplied dead
    fuel moisture (fundamental-engine simplification, documented). Since
    EM-019 the derived default for that value is the load-weighted effective
    moisture of the 1-h / 10-h / 100-h classes, not the plain 1-hour EMC.
    """
    fuel = compute_fuel_bed(resolve_fuel_model_number(fuel_model))
    if fuel_moisture_pct < 0 or wind_kmh_10m < 0 or not 0.0 <= slope_deg < 90.0:
        raise SpreadError(
            "fuel moisture / wind must be >= 0 and slope in [0, 90) degrees"
        )

    sigma = fuel.sigma
    ratio = fuel.beta / fuel.beta_opt

    # Reaction intensity (Rothermel 1972 / Albini 1976).
    a_coef = 133.0 * sigma**-0.7913
    sigma15 = sigma**1.5
    gamma_max = sigma15 / (495.0 + 0.0594 * sigma15)
    gamma = gamma_max * ratio**a_coef * math.exp(a_coef * (1.0 - ratio))
    rm = min(fuel_moisture_pct / 100.0 / fuel.moisture_of_extinction, 1.0)
    eta_m = max(1.0 - 2.59 * rm + 5.11 * rm**2 - 3.52 * rm**3, 0.0)
    eta_s = min(0.174 * EFFECTIVE_MINERAL_CONTENT**-0.19, 1.0)
    ir = gamma * fuel.net_load * HEAT_OF_COMBUSTION_BTU_LB * eta_m * eta_s

    # Propagating flux ratio, effective heating number, heat of preignition.
    xi = math.exp((0.792 + 0.681 * math.sqrt(sigma)) * (fuel.beta + 0.1)) / (
        192.0 + 0.2595 * sigma
    )
    epsilon = math.exp(-138.0 / sigma)
    q_ig = 250.0 + 1116.0 * (fuel_moisture_pct / 100.0)
    heat_sink = (fuel.total_load / fuel.depth_ft) * q_ig * epsilon
    if heat_sink <= 0:
        raise SpreadError("degenerate fuel bed: heat sink must be positive")

    base_ft_min = ir * xi / heat_sink

    # Wind factor: 10 m wind scaled to mid-flame height, then ft/min.
    midflame_mph = (
        wind_kmh_10m * MPH_PER_KMH * midflame_wind_adjustment_factor(fuel.depth_ft)
    )
    wind_ft_min = midflame_mph * FT_MIN_PER_MPH
    c_coef = 7.47 * math.exp(-0.133 * sigma**0.55)
    b_coef = 0.02526 * sigma**0.54
    e_coef = 0.715 * math.exp(-0.000359 * sigma)
    phi_w = (
        c_coef * wind_ft_min**b_coef * ratio**-e_coef if wind_ft_min > 0 else 0.0
    )

    # Slope factor.
    tan_slope = math.tan(math.radians(slope_deg))
    phi_s = 5.275 * fuel.beta**-0.3 * tan_slope**2

    to_m_min = M_PER_FT
    return SpreadRates(
        base_m_min=round(base_ft_min * to_m_min, 3),
        head_m_min=round(base_ft_min * (1.0 + phi_w + phi_s) * to_m_min, 3),
        wind_factor=round(phi_w, 4),
        slope_factor=round(phi_s, 4),
        reaction_intensity=round(ir, 2),
        fuel=fuel,
    )


def _compass_vector(bearing_deg: float) -> tuple[float, float]:
    """Unit vector (east, north) for a compass bearing (0=north, 90=east)."""
    rad = math.radians(bearing_deg)
    return math.sin(rad), math.cos(rad)


def spread_direction_deg(
    wind_from_deg: float,
    wind_factor: float,
    aspect_deg: float,
    slope_deg: float,
    slope_factor: float,
) -> float | None:
    """Resultant spread bearing (direction the fire head moves toward).

    Combines the downwind vector and the upslope vector weighted by their
    Rothermel factors. Returns None when neither drives spread (calm, flat).
    """
    east = north = 0.0
    if wind_factor > 0:
        # Meteorological convention: wind_from is where the wind blows from.
        we, wn = _compass_vector((wind_from_deg + 180.0) % 360.0)
        east += wind_factor * we
        north += wind_factor * wn
    if slope_factor > 0 and slope_deg > 0:
        # Aspect is the downslope bearing; spread runs upslope.
        se, sn = _compass_vector((aspect_deg + 180.0) % 360.0)
        east += slope_factor * se
        north += slope_factor * sn
    if east == 0.0 and north == 0.0:
        return None
    return round(math.degrees(math.atan2(east, north)) % 360.0, 1)


def fire_ellipse_polygon(
    head_m: float,
    back_m: float,
    direction_deg: float | None,
    vertices: int = 36,
) -> list[list[float]]:
    """Local-metric elliptical risk zone with the ignition point at a focus.

    The head vertex sits exactly head_m along the spread direction and the
    rear vertex exactly back_m upwind/uphill; flank distance follows from the
    focus-based polar ellipse r(t) = l / (1 - e*cos(t - dir)). With no driving
    force the polygon is a circle of radius head_m.
    """
    if head_m < 0 or back_m < 0:
        raise SpreadError("ellipse radii must be non-negative")
    if head_m == 0 or back_m == 0:
        return []
    semi_major = (head_m + back_m) / 2.0
    eccentricity = (
        0.0 if direction_deg is None else (head_m - back_m) / (head_m + back_m)
    )
    latus = 2.0 * head_m * back_m / (head_m + back_m)
    points: list[list[float]] = []
    for step in range(vertices):
        theta = 2.0 * math.pi * step / vertices
        radius = (
            semi_major
            if eccentricity == 0.0
            else latus / (1.0 - eccentricity * math.cos(theta))
        )
        # theta measured clockwise from the spread direction, in local ENU:
        bearing = (direction_deg or 0.0) + math.degrees(theta)
        east, north = _compass_vector(bearing)
        points.append([round(radius * east, 2), round(radius * north, 2)])
    points.append(list(points[0]))  # close the ring
    return points


# ---------------------------------------------------------------------------
# EM-016: Fuel-transition-sensitive spread (heterogeneous vegetation)
# ---------------------------------------------------------------------------

# Maximum number of vertices used for the fuel-sensitive polygon.
FUEL_TRANSITION_VERTICES = 72  # 5° resolution for smooth boundary


def _fuel_number_at_offset(
    session: Session,
    lat: float,
    lon: float,
    east_m: float,
    north_m: float,
    default_number: int,
) -> int:
    """Resolve the fuel model number at a local-metric offset from ignition."""
    meters_per_lon = METERS_PER_DEGREE_LAT * max(math.cos(math.radians(lat)), 0.1)
    target_lat = lat + north_m / METERS_PER_DEGREE_LAT
    target_lon = lon + east_m / meters_per_lon
    cover = _nearest_row(session, LandCoverDataPoint, target_lat, target_lon)
    if cover is not None:
        try:
            return resolve_fuel_model_number(str(cover.fuel_model))
        except SpreadError:
            pass
    return default_number


# Sentinel score for land-cover points outside a sample's search box.
_NO_MATCH = -(2**62)


def _batch_fuel_numbers(
    session: Session,
    lat: float,
    lon: float,
    samples: list[tuple[float, float]],
    default_number: int,
) -> list[int]:
    """EM-022 vectorized land-cover sampling for the transition polygon.

    One bbox query replaces the per-vertex ``_nearest_row`` round trips: all
    points inside the union of the sample search boxes are fetched once, then
    for every sample the most recently fetched point within its own ±0.05°
    box wins (numpy argmax over datetime64 scores), mirroring the scalar
    query semantics. Ties on identical ``fetched_at`` resolve to the lowest
    rowid on both paths.
    """
    if not samples:
        return []
    max_offset = max(math.hypot(east, north) for east, north in samples)
    pad = 0.05 + max_offset / METERS_PER_DEGREE_LAT + 0.005
    rows = session.execute(
        select(
            LandCoverDataPoint.latitude,
            LandCoverDataPoint.longitude,
            LandCoverDataPoint.fuel_model,
            LandCoverDataPoint.fetched_at,
        ).where(
            LandCoverDataPoint.latitude.between(lat - pad, lat + pad),
            LandCoverDataPoint.longitude.between(lon - pad, lon + pad),
        )
    ).all()
    numbers = [default_number] * len(samples)
    if not rows:
        return numbers
    point_lat = np.array([float(row[0]) for row in rows])
    point_lon = np.array([float(row[1]) for row in rows])
    fetched = np.array([row[3] for row in rows], dtype="datetime64[ns]").astype("int64")
    meters_per_lon = METERS_PER_DEGREE_LAT * max(math.cos(math.radians(lat)), 0.1)
    sample_lat = np.array([lat + north / METERS_PER_DEGREE_LAT for _, north in samples])
    sample_lon = np.array([lon + east / meters_per_lon for east, _ in samples])
    in_box = (np.abs(sample_lat[:, None] - point_lat[None, :]) <= 0.05) & (
        np.abs(sample_lon[:, None] - point_lon[None, :]) <= 0.05
    )
    scores = np.where(in_box, fetched[None, :], _NO_MATCH)
    best = scores.argmax(axis=1)
    for idx, col in enumerate(best):
        if scores[idx, col] == _NO_MATCH:
            continue
        try:
            numbers[idx] = resolve_fuel_model_number(str(rows[col][2]))
        except SpreadError:
            pass  # unknown label: keep the default, like the scalar path
    return numbers


def fuel_transition_polygon(
    session: Session,
    head_m: float,
    back_m: float,
    direction_deg: float | None,
    base_fuel_number: int,
    ignition_lat: float = 0.0,
    ignition_lon: float = 0.0,
    vertices: int = FUEL_TRANSITION_VERTICES,
    settings: Any = None,
) -> tuple[list[list[float]], list[dict[str, Any]]]:
    """Generate a fuel-sensitive irregular risk-zone polygon.

    For each vertex along the nominal ellipse boundary, the local fuel model
    is sampled and the radius is scaled by the ratio of the local ROS to the
    base ROS.  Returns (local_metric_points, fuel_zone_metadata).

    When the fire front reaches a less-flammable zone (e.g. agriculture from
    pine), the polygon is pinched inward; toward more-flammable vegetation
    (e.g. grass from chaparral), it bulges outward.

    With EM-022 (SPREAD_PERF_ENABLED) the vertex sampling runs batched and
    vectorized (one land-cover query per polygon instead of one per vertex);
    both paths produce identical rings.
    """
    if head_m <= 0 or back_m <= 0:
        return [], []

    # Pre-compute base rate for the ignition-point fuel (reference).
    base_rates = spread_rates(base_fuel_number, 8.0, 0.0, 0.0)  # calm, flat
    base_ros = base_rates.head_m_min if base_rates.head_m_min > 0 else 1.0

    semi_major = (head_m + back_m) / 2.0
    eccentricity = (
        0.0 if direction_deg is None else (head_m - back_m) / (head_m + back_m)
    )
    latus = 2.0 * head_m * back_m / (head_m + back_m)

    # Nominal front geometry per vertex: (radius, east unit, north unit).
    geometry: list[tuple[float, float, float]] = []
    for step in range(vertices):
        theta = 2.0 * math.pi * step / vertices
        nominal_r = (
            semi_major
            if eccentricity == 0.0
            else latus / (1.0 - eccentricity * math.cos(theta))
        )
        bearing = (direction_deg or 0.0) + math.degrees(theta)
        east, north = _compass_vector(bearing)
        geometry.append((nominal_r, east, north))

    if perf_enabled(settings):
        # EM-022: vectorized batch sampling, one query for all vertices.
        samples = [(r * e, r * n) for r, e, n in geometry]
        numbers = _batch_fuel_numbers(
            session, ignition_lat, ignition_lon, samples, base_fuel_number
        )
    else:
        numbers = [
            _fuel_number_at_offset(
                session,
                ignition_lat,
                ignition_lon,
                nominal_r * east,
                nominal_r * north,
                base_fuel_number,
            )
            for nominal_r, east, north in geometry
        ]

    points: list[list[float]] = []
    zones: list[dict[str, Any]] = []
    seen_fuel: dict[int, int] = {}  # fuel_number -> vertex count

    for (nominal_r, east, north), local_fuel_num in zip(geometry, numbers):
        # Compute local ROS ratio (calm, flat — same weather, different fuel)
        if local_fuel_num != base_fuel_number:
            local_rates = spread_rates(local_fuel_num, 8.0, 0.0, 0.0)
            local_ros = local_rates.head_m_min if local_rates.head_m_min > 0 else 0.0
            # Scale factor: ratio of local to base fuel ROS (capped 0.2..3.0)
            scale = max(0.2, min(3.0, local_ros / base_ros)) if base_ros > 0 else 1.0
        else:
            scale = 1.0

        adjusted_r = nominal_r * scale
        points.append([round(adjusted_r * east, 2), round(adjusted_r * north, 2)])

        seen_fuel[local_fuel_num] = seen_fuel.get(local_fuel_num, 0) + 1

    points.append(list(points[0]))  # close ring

    # Build zone metadata
    for fuel_num, count in sorted(seen_fuel.items()):
        try:
            bed = compute_fuel_bed(fuel_num)
            zones.append(
                {
                    "fuel_model_number": fuel_num,
                    "fuel_model_name": bed.name,
                    "vertex_count": count,
                    "percentage": round(100.0 * count / vertices, 1),
                }
            )
        except SpreadError:
            pass

    return points, zones


def polygon_area_m2(points: list[list[float]]) -> float:
    """Shoelace area of a closed local-metric ring [m2]."""
    total = 0.0
    for idx in range(len(points) - 1):
        x1, y1 = points[idx]
        x2, y2 = points[idx + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def project_polygon(
    local_points: list[list[float]], latitude: float, longitude: float
) -> list[list[float]]:
    """Project a local-metric ENU ring onto [lon, lat] WGS-84 coordinates."""
    meters_per_lon = METERS_PER_DEGREE_LAT * max(math.cos(math.radians(latitude)), 0.1)
    ring: list[list[float]] = []
    for east_m, north_m in local_points:
        lat = latitude + north_m / METERS_PER_DEGREE_LAT
        lon = longitude + east_m / meters_per_lon
        ring.append([round(lon, 6), round(lat, 6)])
    return ring


def _nearest_row(session: Session, model: Any, lat: float, lon: float) -> Any:
    """Most recently fetched data point of `model` within ~5.5 km of a spot."""
    return session.scalars(
        select(model)
        .where(
            model.latitude.between(lat - 0.05, lat + 0.05),
            model.longitude.between(lon - 0.05, lon + 0.05),
        )
        .order_by(model.fetched_at.desc())
        .limit(1)
    ).first()


# EM-022: attributes the engine reads from each cached input layer.
_LAYER_SNAPSHOT_FIELDS = {
    "WeatherDataPoint": ("wind_speed", "wind_deg", "temperature", "humidity"),
    "TopographyDataPoint": ("slope", "aspect"),
    "LandCoverDataPoint": ("fuel_model",),
}


def _nearest_row_view(session: Session, model: Any, lat: float, lon: float) -> Any:
    """Cache-safe attribute snapshot of the nearest row (None stays None)."""
    row = _nearest_row(session, model, lat, lon)
    if row is None:
        return None
    fields = _LAYER_SNAPSHOT_FIELDS.get(model.__name__, ())
    return RowView(**{name: getattr(row, name) for name in fields})


def _nearest_row_cached(
    session: Session, model: Any, lat: float, lon: float, settings: Any
) -> Any:
    """Nearest-row lookup behind the EM-022 quantized-grid TTL cache.

    With SPREAD_PERF_ENABLED off (the default for settings stubs) this is
    the plain scalar query, so engine behaviour is unchanged elsewhere.
    """
    if not perf_enabled(settings):
        return _nearest_row(session, model, lat, lon)
    return cached_nearest_value(
        session,
        model.__name__,
        lat,
        lon,
        lambda: _nearest_row_view(session, model, lat, lon),
        settings,
    )


def resolve_inputs(
    session: Session, req: dict[str, Any], settings: Any = None
) -> dict[str, Any]:
    """Fill missing spread inputs from the stored pilot-layer data.

    Priority: explicit request value > nearest stored observation >
    deterministic fallback (synthetic CORINE fuel class, calm flat weather).
    Fuel moisture comes from the EM-019 per-class dead fuel model unless an
    explicit value is supplied or the model is switched off in settings.
    Returns the merged inputs plus a per-field provenance map.
    """
    lat = float(req["latitude"])
    lon = float(req["longitude"])
    provenance: dict[str, str] = {}
    resolved: dict[str, Any] = {"latitude": lat, "longitude": lon}

    def take(key: str, value: Any) -> Any:
        if value is not None:
            resolved[key] = value
            provenance[key] = "request"
        return value

    # Wind / temperature / humidity.
    weather = _nearest_row_cached(session, WeatherDataPoint, lat, lon, settings)
    if take("wind_speed_kmh", req.get("wind_speed_kmh")) is None:
        if weather is not None:
            # Stored OpenWeather values are metric (m/s) -> km/h.
            resolved["wind_speed_kmh"] = round(float(weather.wind_speed) * MS_TO_KMH, 1)
            provenance["wind_speed_kmh"] = "weather_data_points"
        else:
            resolved["wind_speed_kmh"] = 0.0
            provenance["wind_speed_kmh"] = "fallback_calm"
    if take("wind_from_deg", req.get("wind_from_deg")) is None:
        resolved["wind_from_deg"] = (
            float(weather.wind_deg) if weather is not None else 0.0
        )
        provenance["wind_from_deg"] = (
            "weather_data_points" if weather is not None else "fallback_north"
        )
    if take("air_temp_c", req.get("air_temp_c")) is None:
        resolved["air_temp_c"] = (
            float(weather.temperature) if weather is not None else 25.0
        )
        provenance["air_temp_c"] = (
            "weather_data_points" if weather is not None else "fallback_25c"
        )
    if take("relative_humidity_pct", req.get("relative_humidity_pct")) is None:
        resolved["relative_humidity_pct"] = (
            float(weather.humidity) if weather is not None else 40.0
        )
        provenance["relative_humidity_pct"] = (
            "weather_data_points" if weather is not None else "fallback_40pct"
        )

    # Slope and aspect.
    topo = _nearest_row_cached(session, TopographyDataPoint, lat, lon, settings)
    if take("slope_deg", req.get("slope_deg")) is None:
        resolved["slope_deg"] = float(topo.slope) if topo is not None else 0.0
        provenance["slope_deg"] = "topography_data_points" if topo else "fallback_flat"
    if take("aspect_deg", req.get("aspect_deg")) is None:
        resolved["aspect_deg"] = float(topo.aspect) if topo is not None else 0.0
        provenance["aspect_deg"] = "topography_data_points" if topo else "fallback_flat"

    # Fuel class.
    fuel_label = req.get("fuel_model")
    if fuel_label is not None:
        resolved["fuel_model"] = fuel_label
        provenance["fuel_model"] = "request"
    else:
        cover = _nearest_row_cached(session, LandCoverDataPoint, lat, lon, settings)
        if cover is not None:
            resolved["fuel_model"] = str(cover.fuel_model)
            provenance["fuel_model"] = "land_cover_data_points"
        else:
            synthetic = LandCoverFuelService().fetch_land_cover_fuel(lat, lon)
            resolved["fuel_model"] = synthetic.fuel_model
            provenance["fuel_model"] = "corine_synthetic"
    resolved["fuel_model_number"] = resolve_fuel_model_number(resolved["fuel_model"])

    # Fuel moisture: explicit value, EM-019 per-class dead fuel model, or
    # the plain Van Wagner 1-hour equilibrium (legacy behaviour).
    if take("fuel_moisture_pct", req.get("fuel_moisture_pct")) is None:
        temp = float(resolved["air_temp_c"])
        rh = float(resolved["relative_humidity_pct"])
        if bool(getattr(settings, "FUEL_MOISTURE_MODEL_ENABLED", True)):
            try:
                classes = dead_fuel_moisture(
                    temp,
                    rh,
                    temp_amplitude_c=float(
                        getattr(
                            settings,
                            "FUEL_MOISTURE_DIURNAL_TEMP_AMPLITUDE_C",
                            8.0,
                        )
                    ),
                    rh_amplitude_pct=float(
                        getattr(
                            settings,
                            "FUEL_MOISTURE_DIURNAL_RH_AMPLITUDE_PCT",
                            25.0,
                        )
                    ),
                    conditioning_hours=int(
                        getattr(settings, "FUEL_MOISTURE_CONDITIONING_HOURS", 48)
                    ),
                )
            except FuelMoistureError as exc:
                raise SpreadError(f"fuel moisture model: {exc}") from exc
            resolved["fuel_moisture_1h_pct"] = classes["moisture_1h_pct"]
            resolved["fuel_moisture_10h_pct"] = classes["moisture_10h_pct"]
            resolved["fuel_moisture_100h_pct"] = classes["moisture_100h_pct"]
            resolved["fuel_moisture_pct"] = effective_dead_fuel_moisture(
                int(resolved["fuel_model_number"]), classes
            )
            provenance["fuel_moisture_pct"] = FUEL_MOISTURE_MODEL_NAME
        else:
            resolved["fuel_moisture_pct"] = round(
                equilibrium_moisture_content(temp, rh), 1
            )
            provenance["fuel_moisture_pct"] = "van_wagner_emc"

    return {"inputs": resolved, "provenance": provenance}


def horizon_minutes(settings: Any, override: list[int] | None) -> list[int]:
    """Resolve the forecast horizons from settings or request override."""
    horizons = (
        override
        if override is not None
        else list(getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120]))
    )
    clean = sorted({int(h) for h in horizons if int(h) > 0})
    if not clean:
        raise SpreadError("at least one positive forecast horizon is required")
    return clean


def predict_spread(
    session: Session, settings: Any, req: dict[str, Any]
) -> dict[str, Any]:
    """Run the Rothermel engine for one ignition point and every horizon.

    Accepts explicit inputs and/or stored pilot data (see resolve_inputs).
    When an ``event_key`` is provided the horizon polygons are persisted as
    FireForecast rows. The computation itself is deterministic.
    """
    if req.get("latitude") is None or req.get("longitude") is None:
        raise SpreadError("latitude and longitude are required")
    lat = float(req["latitude"])
    lon = float(req["longitude"])
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise SpreadError(f"coordinate out of range: {lat}, {lon}")

    resolved = resolve_inputs(session, req, settings)
    inputs = resolved["inputs"]
    horizons = horizon_minutes(settings, req.get("horizon_minutes"))
    vertices = int(getattr(settings, "SPREAD_POLYGON_VERTICES", 36))
    model_name = str(getattr(settings, "SPREAD_MODEL_NAME", "rothermel_v1"))
    fuel_transition = bool(getattr(settings, "FUEL_TRANSITION_ENABLED", True))
    # EM-021: active natural barriers (water clip / partial slowdown).
    barriers_enabled = bool(getattr(settings, "SPREAD_BARRIERS_ENABLED", True))
    # EM-022: barrier loads go through the layer cache when perf is enabled.
    barriers = load_active_barriers(session, settings) if barriers_enabled else []

    rates = spread_rates(
        inputs["fuel_model_number"],
        float(inputs["fuel_moisture_pct"]),
        float(inputs["wind_speed_kmh"]),
        float(inputs["slope_deg"]),
    )
    direction = spread_direction_deg(
        float(inputs["wind_from_deg"]),
        rates.wind_factor,
        float(inputs["aspect_deg"]),
        float(inputs["slope_deg"]),
        rates.slope_factor,
    )

    started = utc_now()
    forecasts: list[dict[str, Any]] = []
    event_key = req.get("event_key")
    all_fuel_zones: list[dict[str, Any]] = []
    for minutes in horizons:
        head_m = rates.head_m_min * minutes
        back_m = rates.base_m_min * minutes

        if fuel_transition:
            # EM-016: fuel-sensitive irregular polygon
            local, zones = fuel_transition_polygon(
                session,
                head_m,
                back_m,
                direction,
                inputs["fuel_model_number"],
                ignition_lat=lat,
                ignition_lon=lon,
                vertices=FUEL_TRANSITION_VERTICES,
                settings=settings,
            )
            if zones and not all_fuel_zones:
                all_fuel_zones = zones
        else:
            local = fire_ellipse_polygon(head_m, back_m, direction, vertices)

        if local and barriers:
            # EM-021: clip the ring at water bodies, slow it at roads/streams
            # before projection so risk zones never spill into the sea.
            local = mask_local_ring(lat, lon, local, barriers)

        ring = project_polygon(local, lat, lon)
        area_ha = round(polygon_area_m2(local) / 10000.0, 3) if local else 0.0
        geometry_wkt = ""
        if ring:
            geometry_wkt = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"
        forecasts.append(
            {
                "horizon_minutes": minutes,
                "forecast_for": to_utc_iso(started + timedelta(minutes=minutes)),
                "rate_of_spread_m_min": rates.head_m_min,
                "base_rate_m_min": rates.base_m_min,
                "spread_direction_deg": direction,
                "head_distance_m": round(head_m, 1),
                "back_distance_m": round(back_m, 1),
                "area_ha": area_ha,
                "polygon_geojson": {
                    "type": "Polygon",
                    "coordinates": [ring] if ring else [],
                },
                "geometry_wkt": geometry_wkt,
            }
        )

    if event_key:
        # EM-020: the per-field provenance map is stored alongside the inputs
        # so the uncertainty layer can score model confidence without re-
        # resolving layers. Debounce comparisons read fixed keys only.
        stored_inputs = {k: v for k, v in inputs.items() if k != "fuel_model_number"}
        stored_inputs["provenance"] = resolved["provenance"]
        inputs_json = json.dumps(stored_inputs, sort_keys=True, default=str)
        for item in forecasts:
            session.add(
                FireForecast(
                    event_key=str(event_key),
                    model_name=model_name,
                    latitude=lat,
                    longitude=lon,
                    predicted_area_ha=item["area_ha"],
                    geometry_wkt=item["geometry_wkt"] or "POLYGON(EMPTY)",
                    forecast_for=started
                    + timedelta(minutes=int(item["horizon_minutes"])),
                    horizon_minutes=int(item["horizon_minutes"]),
                    rate_of_spread_m_per_min=item["rate_of_spread_m_min"],
                    spread_direction_deg=item["spread_direction_deg"] or 0.0,
                    inputs_json=inputs_json,
                )
            )
        session.commit()

    fuel = rates.fuel
    return {
        "model_name": model_name,
        "generated_at": to_utc_iso(started),
        "latitude": lat,
        "longitude": lon,
        "event_key": event_key,
        "inputs": {**inputs, "fuel_model_name": fuel.name},
        "input_provenance": resolved["provenance"],
        "fuel_bed": {
            "number": fuel.number,
            "name": fuel.name,
            "sigma_ft": round(fuel.sigma, 1),
            "beta": round(fuel.beta, 6),
            "beta_opt": round(fuel.beta_opt, 6),
            "depth_ft": fuel.depth_ft,
            "moisture_of_extinction_pct": round(fuel.moisture_of_extinction * 100.0, 1),
        },
        "wind_factor": rates.wind_factor,
        "slope_factor": rates.slope_factor,
        "reaction_intensity_btu_ft2_min": rates.reaction_intensity,
        "spread_direction_deg": direction,
        "fuel_transition": fuel_transition,
        "natural_barriers": {
            "enabled": barriers_enabled,
            "active": len(barriers),
            "types": sorted({str(b["barrier_type"]) for b in barriers}),
        },
        "fuel_zones": all_fuel_zones,
        "forecasts": forecasts,
    }


def fuel_model_catalog() -> list[dict[str, Any]]:
    """Describe every standard fuel model with its mapped intermediates."""
    catalog: list[dict[str, Any]] = []
    for number in sorted(FUEL_MODEL_RECORDS):
        bed = compute_fuel_bed(number)
        catalog.append(
            {
                "number": bed.number,
                "name": bed.name,
                "depth_ft": bed.depth_ft,
                "moisture_of_extinction_pct": round(
                    bed.moisture_of_extinction * 100.0, 1
                ),
                "total_load_lb_ft2": round(bed.total_load, 3),
                "sigma_ft2_ft3": round(bed.sigma, 1),
                "beta": round(bed.beta, 6),
                "project_aliases": sorted(
                    alias
                    for alias, target in PROJECT_FUEL_ALIASES.items()
                    if target == number
                ),
            }
        )
    return catalog


def list_event_forecasts(
    session: Session, event_key: str | None
) -> list[dict[str, Any]]:
    """Stored spread forecasts, newest first; optionally for one event."""
    query = select(FireForecast).order_by(FireForecast.created_at.desc())
    if event_key:
        query = query.where(FireForecast.event_key == event_key)
    rows = session.scalars(query.limit(200)).all()
    return [row.as_dict for row in rows]


def latest_forecast_count(session: Session) -> int:
    """Total stored forecast rows (for smoke checks in tests/dashboard)."""
    return int(session.scalar(select(func.count(FireForecast.id))) or 0)
