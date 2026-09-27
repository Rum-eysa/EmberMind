"""EM-020 spread-forecast uncertainty: optimistic / expected / pessimistic
envelope per horizon plus a model-confidence indicator.

The envelope comes from a deterministic multi-run ensemble (nine runs) that
perturbs the driving wind: direction +/-10 deg and speed +/-15 % (both
tunable via settings). For every horizon the runs are combined per compass
bearing into an outer (pessimistic) and inner (optimistic) ellipse envelope
around the unperturbed expected polygon, so a commander can see how far the
fire might actually reach in each direction instead of trusting one line.

The model-confidence score weighs the provenance of the resolved inputs
(see spread.resolve_inputs): real observations or explicit request values
weigh fully, model-derived values (e.g. EM-019 moisture) partially and
deterministic fallbacks the least.
"""
from datetime import timedelta
from math import cos, radians, sin
from typing import Any

from sqlalchemy.orm import Session

from src.services.barriers import load_active_barriers, mask_local_ring
from src.services.spread import (
    SpreadError,
    fire_ellipse_polygon,
    horizon_minutes,
    polygon_area_m2,
    project_polygon,
    resolve_inputs,
    spread_direction_deg,
    spread_rates,
)
from src.utils.timeutils import to_utc_iso, utc_now

ENSEMBLE_MODEL_NAME = "wind_ensemble_v1"
DEFAULT_WIND_DIR_DELTA_DEG = 10.0
DEFAULT_WIND_SPEED_FRACTION = 0.15

# Provenance source -> reliability weight in [0, 1] for the model-confidence
# indicator. Anything starting with "fallback" uses FALLBACK_WEIGHT; unknown
# sources are treated as neutral.
_SOURCE_WEIGHTS = {
    "request": 1.0,
    "weather_data_points": 0.9,
    "topography_data_points": 0.9,
    "land_cover_data_points": 0.9,
    "fire_perimeter_buffer": 0.9,
    "fuel_transition_polygon": 0.85,
    "dead_fuel_moisture_v1": 0.7,
    "van_wagner_emc": 0.7,
    "corine_synthetic": 0.6,
}
_FALLBACK_WEIGHT = 0.2
_UNKNOWN_WEIGHT = 0.5

_CONFIDENCE_BANDS = {"high": "Yüksek", "moderate": "Orta", "low": "Düşük"}


def perturbation_settings(settings: Any) -> tuple[float, float]:
    """(dir_delta_deg, speed_fraction) wind perturbation from settings."""
    dir_delta = float(
        getattr(
            settings,
            "SPREAD_UNCERTAINTY_WIND_DIR_DELTA_DEG",
            DEFAULT_WIND_DIR_DELTA_DEG,
        )
    )
    fraction = float(
        getattr(
            settings,
            "SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION",
            DEFAULT_WIND_SPEED_FRACTION,
        )
    )
    if dir_delta < 0 or not 0 <= fraction < 1:
        raise SpreadError("invalid uncertainty perturbation settings")
    return dir_delta, fraction


def ensemble_scenarios(
    dir_delta_deg: float, speed_fraction: float
) -> list[dict[str, Any]]:
    """The deterministic multi-run grid: 3 wind directions x 3 wind speeds."""
    scenarios: list[dict[str, Any]] = []
    for factor in (1.0 - speed_fraction, 1.0, 1.0 + speed_fraction):
        for delta in (-dir_delta_deg, 0.0, dir_delta_deg):
            scenarios.append(
                {
                    "name": f"dir{delta:+g}_spd{factor:g}",
                    "wind_dir_delta_deg": round(delta, 4),
                    "wind_speed_factor": round(factor, 4),
                }
            )
    return scenarios


def _ellipse_radius(
    head_m: float, back_m: float, direction_deg: float | None, bearing_deg: float
) -> float:
    """Focus-based ellipse radius r = l / (1 - e*cos(bearing - direction)).

    Matches fire_ellipse_polygon so envelope rings share its geometry; a
    calm/flat fire (no driving direction) is a circle of radius head_m.
    """
    if direction_deg is None or head_m <= 0:
        return max(head_m, 0.0)
    if back_m <= 0:
        return 0.0 if bearing_deg != direction_deg else head_m
    total = head_m + back_m
    eccentricity = (head_m - back_m) / total
    latus = 2.0 * head_m * back_m / total
    angle = radians(bearing_deg - direction_deg)
    return latus / (1.0 - eccentricity * cos(angle))


def _envelope_ring(
    runs: list[dict[str, Any]],
    minutes: int,
    vertices: int,
    extreme: str,
) -> list[list[float]]:
    """Local-metric min/max radius envelope ring over the ensemble runs."""
    points: list[list[float]] = []
    for step in range(vertices):
        bearing = 360.0 * step / vertices
        radii = [
            _ellipse_radius(
                run["head_m_min"] * minutes,
                run["base_m_min"] * minutes,
                run["direction_deg"],
                bearing,
            )
            for run in runs
        ]
        radius = min(radii) if extreme == "optimistic" else max(radii)
        points.append(
            [
                round(radius * sin(radians(bearing)), 2),
                round(radius * cos(radians(bearing)), 2),
            ]
        )
    points.append(list(points[0]))  # close ring
    return points


def _band_summary(
    runs: list[dict[str, Any]], minutes: int, extreme: str
) -> dict[str, Any]:
    """Head/back distance and ROS of the best/worst ensemble run."""
    if extreme == "optimistic":
        best = min(runs, key=lambda r: (r["head_m_min"], r["name"]))
    else:
        best = max(runs, key=lambda r: (r["head_m_min"], r["name"]))
    return {
        "rate_of_spread_m_min": round(best["head_m_min"], 3),
        "head_distance_m": round(best["head_m_min"] * minutes, 1),
        "back_distance_m": round(best["base_m_min"] * minutes, 1),
        "spread_direction_deg": best["direction_deg"],
        "scenario": {
            "name": best["name"],
            "wind_dir_delta_deg": best["wind_dir_delta_deg"],
            "wind_speed_factor": best["wind_speed_factor"],
        },
    }


def envelope_from_inputs(
    session: Session,
    settings: Any,
    inputs: dict[str, Any],
    horizons: list[int],
) -> dict[str, Any]:
    """Run the wind ensemble and build the per-horizon uncertainty envelope.

    Pure function of the resolved engine inputs; deterministic. The expected
    member is the unperturbed EM-015 run; optimistic/pessimistic rings are the
    per-bearing min/max over all ensemble runs.
    """
    dir_delta, speed_fraction = perturbation_settings(settings)
    vertices = int(getattr(settings, "SPREAD_POLYGON_VERTICES", 36))
    lat = float(inputs["latitude"])
    lon = float(inputs["longitude"])
    fuel_number = int(inputs["fuel_model_number"])
    moisture = float(inputs["fuel_moisture_pct"])
    base_wind = float(inputs["wind_speed_kmh"])
    base_from = float(inputs["wind_from_deg"])
    slope = float(inputs["slope_deg"])

    runs: list[dict[str, Any]] = []
    for scenario in ensemble_scenarios(dir_delta, speed_fraction):
        wind = max(base_wind * scenario["wind_speed_factor"], 0.0)
        wind_from = (base_from + scenario["wind_dir_delta_deg"]) % 360.0
        rates = spread_rates(fuel_number, moisture, wind, slope)
        direction = spread_direction_deg(
            wind_from,
            rates.wind_factor,
            float(inputs["aspect_deg"]),
            slope,
            rates.slope_factor,
        )
        runs.append(
            {
                **scenario,
                "wind_speed_kmh": round(wind, 2),
                "wind_from_deg": round(wind_from, 2),
                "head_m_min": rates.head_m_min,
                "base_m_min": rates.base_m_min,
                "direction_deg": direction,
            }
        )

    expected_run = next(
        r
        for r in runs
        if r["wind_dir_delta_deg"] == 0.0 and r["wind_speed_factor"] == 1.0
    )
    # EM-021: the ensemble rings respect active natural barriers as well.
    barriers_enabled = bool(getattr(settings, "SPREAD_BARRIERS_ENABLED", True))
    barriers = load_active_barriers(session) if barriers_enabled else []

    def _masked(local: list[list[float]]) -> list[list[float]]:
        if local and barriers:
            return mask_local_ring(lat, lon, local, barriers)
        return local

    started = utc_now()
    horizon_bands: list[dict[str, Any]] = []
    for minutes in horizons:
        expected_local = fire_ellipse_polygon(
            expected_run["head_m_min"] * minutes,
            expected_run["base_m_min"] * minutes,
            expected_run["direction_deg"],
            vertices,
        )
        expected_local = _masked(expected_local)
        expected_ring = project_polygon(expected_local, lat, lon)
        bands: dict[str, Any] = {"horizon_minutes": minutes}
        for extreme in ("optimistic", "pessimistic"):
            local = _masked(_envelope_ring(runs, minutes, vertices, extreme))
            ring = project_polygon(local, lat, lon)
            area_ha = round(polygon_area_m2(local) / 10000.0, 3)
            bands[extreme] = {
                **_band_summary(runs, minutes, extreme),
                "area_ha": area_ha,
                "polygon_geojson": {"type": "Polygon", "coordinates": [ring]},
            }
        expected_area = (
            round(polygon_area_m2(expected_local) / 10000.0, 3)
            if expected_local
            else 0.0
        )
        bands["expected"] = {
            "rate_of_spread_m_min": round(expected_run["head_m_min"], 3),
            "head_distance_m": round(expected_run["head_m_min"] * minutes, 1),
            "back_distance_m": round(expected_run["base_m_min"] * minutes, 1),
            "spread_direction_deg": expected_run["direction_deg"],
            "area_ha": expected_area,
            "polygon_geojson": {"type": "Polygon", "coordinates": [expected_ring]},
        }
        bands["band_width_m"] = round(
            bands["pessimistic"]["head_distance_m"]
            - bands["optimistic"]["head_distance_m"],
            1,
        )
        bands["forecast_for"] = (started + timedelta(minutes=minutes)).isoformat()
        horizon_bands.append(bands)

    return {
        "model": ENSEMBLE_MODEL_NAME,
        "perturbation": {
            "wind_dir_delta_deg": dir_delta,
            "wind_speed_fraction": speed_fraction,
            "runs": len(runs),
        },
        "natural_barriers": {
            "enabled": barriers_enabled,
            "active": len(barriers),
        },
        "horizons": horizon_bands,
    }


def _source_weight(provenance_source: str) -> float:
    """Reliability weight of one input-provenance source label."""
    if provenance_source in _SOURCE_WEIGHTS:
        return _SOURCE_WEIGHTS[provenance_source]
    if str(provenance_source).startswith("fallback"):
        return _FALLBACK_WEIGHT
    return _UNKNOWN_WEIGHT


def model_confidence(provenance: dict[str, str] | None) -> dict[str, Any]:
    """Score how trustworthy a forecast is from its input provenance.

    Returns a 0..1 score plus a coarse band (high/moderate/low). Without any
    provenance information the confidence is reported as unknown instead of
    pretending the inputs were observed.
    """
    if not provenance:
        return {
            "score": None,
            "band": "unknown",
            "label": "Bilinmiyor",
            "inputs_scored": 0,
        }
    weights = [_source_weight(str(src)) for src in provenance.values()]
    score = round(sum(weights) / len(weights), 2)
    if score >= 0.85:
        band = "high"
    elif score >= 0.6:
        band = "moderate"
    else:
        band = "low"
    return {
        "score": score,
        "band": band,
        "label": _CONFIDENCE_BANDS[band],
        "inputs_scored": len(weights),
    }


def uncertainty_envelope(
    session: Session, settings: Any, req: dict[str, Any]
) -> dict[str, Any]:
    """Resolve spread inputs, then run the EM-020 ensemble for the request."""
    if req.get("latitude") is None or req.get("longitude") is None:
        raise SpreadError("latitude and longitude are required")
    lat = float(req["latitude"])
    lon = float(req["longitude"])
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise SpreadError(f"coordinate out of range: {lat}, {lon}")
    resolved = resolve_inputs(session, req, settings)
    horizons = horizon_minutes(settings, req.get("horizon_minutes"))
    envelope = envelope_from_inputs(session, settings, resolved["inputs"], horizons)
    return {
        "generated_at": to_utc_iso(utc_now()),
        "latitude": lat,
        "longitude": lon,
        "event_key": req.get("event_key"),
        "inputs": resolved["inputs"],
        "input_provenance": resolved["provenance"],
        "model_confidence": model_confidence(resolved["provenance"]),
        **envelope,
    }
