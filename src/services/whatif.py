"""Wind what-if & dynamic recompute (EM-055, Epic E6).

As an operator I want to ask "what if the wind rotated 45 degrees?" and see the
answer in seconds: fresh risk-zone polygons, a recalculated capacity gap and an
updated threat recommendation, with the original and the scenario side by side.

This service drives the EM-015 Rothermel engine twice from the same resolved
inputs — once unperturbed (the *original*) and once with the operator's wind
direction/speed change applied (the *scenario*) — purely in memory. Because
``spread.predict_spread`` only persists when an ``event_key`` is supplied, and
we never pass one here, a what-if never touches the database; both sides are
live recomputations compared on equal footing.

Capacity gap is expressed in EM-028's single normalised unit: the demand is the
scenario's area growth in hectares/hour, the supply is the effective
suppression capacity of the available inventory, and the gap is their
difference. The recommendations reuse the EM-023 exposure ranking but against
the ephemeral scenario polygons, so a commander sees exactly which assets
become newly threatened when the wind turns.
"""
from datetime import timedelta
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from src.models.spatial import FireForecast
from src.services.capacity import effective_capacity
from src.services.exposure import (
    _candidate_elements,  # noqa: PLC2701 - reuse the EM-023 ranking engine
    _DEFAULT_MAX_HORIZON,  # noqa: PLC2701
    _first_impact,  # noqa: PLC2701
    _grouped_bbox,  # noqa: PLC2701
    _load_shape,  # noqa: PLC2701
    _polygons_from_rows,  # noqa: PLC2701
    _priority_score,  # noqa: PLC2701
)
from src.services.spread import predict_spread
from src.utils.timeutils import to_utc_iso, utc_now

WHATIF_MODEL_NAME = "wind_whatif_v1"
WHATIF_ATTRIBUTION = (
    "What-if rüzgâr senaryosu: Rothermel canlı yeniden hesaplama (EM-055)"
)
WHATIF_PERSISTENCE = "none"
DEFAULT_RECOMPUTE_TARGET_SECONDS = 10.0
# Fallback used only when a settings object omits the target key entirely.
_TARGET_ATTR = "WHATIF_RECOMPUTE_TARGET_SECONDS"
# Wind scenario bounds for the operator sliders / overrides.
_MAX_WIND_SPEED_KMH = 200.0
_MAX_WIND_SPEED_FACTOR = 5.0


class WhatIfError(RuntimeError):
    """Raised for invalid what-if inputs (bad coordinates or wind values)."""


def recompute_target_seconds(settings: Any) -> float:
    """Wall-clock budget (s) the recomputation is expected to stay under."""
    try:
        target = float(
            getattr(settings, _TARGET_ATTR, DEFAULT_RECOMPUTE_TARGET_SECONDS)
        )
    except (TypeError, ValueError):
        return DEFAULT_RECOMPUTE_TARGET_SECONDS
    return target if target > 0 else DEFAULT_RECOMPUTE_TARGET_SECONDS


def _require_coordinate(req: dict[str, Any], key: str) -> float:
    raw = req.get(key)
    if raw is None:
        raise WhatIfError(f"{key} is required for a what-if recompute")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise WhatIfError(f"{key} must be numeric") from exc
    return value


def _validate_wind(req: dict[str, Any]) -> None:
    """Range-check the operator wind knobs before any engine work happens."""
    speed = req.get("wind_speed_kmh")
    if speed is not None:
        speed = float(speed)
        if not 0.0 <= speed <= _MAX_WIND_SPEED_KMH:
            raise WhatIfError(
                f"wind_speed_kmh must be within [0, {_MAX_WIND_SPEED_KMH}]"
            )
    from_deg = req.get("wind_from_deg")
    if from_deg is not None:
        from_deg = float(from_deg)
        if not 0.0 <= from_deg < 360.0:
            raise WhatIfError("wind_from_deg must be within [0, 360)")
    delta = req.get("wind_rotation_delta_deg")
    if delta is not None:
        delta = float(delta)
        if not -360.0 < delta < 360.0:
            raise WhatIfError("wind_rotation_delta_deg must be within (-360, 360)")
    factor = req.get("wind_speed_factor")
    if factor is not None:
        factor = float(factor)
        if not 0.0 <= factor <= _MAX_WIND_SPEED_FACTOR:
            raise WhatIfError(
                f"wind_speed_factor must be within [0, {_MAX_WIND_SPEED_FACTOR}]"
            )


def _predict_request(
    req: dict[str, Any], wind: dict[str, float] | None = None
) -> dict[str, Any]:
    """Assemble a persist-free predict_spread payload with a resolved wind.

    When ``wind`` is supplied its values take over; otherwise the request's own
    wind (the operator's known base condition) is forwarded so the original run
    reflects it instead of falling back to stored/calm weather.
    """
    active = wind or {}
    return {
        "latitude": req["latitude"],
        "longitude": req["longitude"],
        "event_key": None,  # a what-if never writes FireForecast rows
        "wind_speed_kmh": active.get("wind_speed_kmh", req.get("wind_speed_kmh")),
        "wind_from_deg": active.get("wind_from_deg", req.get("wind_from_deg")),
        "air_temp_c": req.get("air_temp_c"),
        "relative_humidity_pct": req.get("relative_humidity_pct"),
        "fuel_moisture_pct": req.get("fuel_moisture_pct"),
        "slope_deg": req.get("slope_deg"),
        "aspect_deg": req.get("aspect_deg"),
        "fuel_model": req.get("fuel_model"),
        "horizon_minutes": req.get("horizon_minutes"),
    }


def _resolve_scenario_wind(
    base: dict[str, float], req: dict[str, Any]
) -> dict[str, float]:
    """Perturb the resolved base wind with the operator's rotation and factor.

    The request's own wind is the *current base condition* (shared by the
    original and the scenario); the sliders only contribute the rotation delta
    and the speed factor, so a what-if stays a controlled change of one knob.
    """
    base_from = float(base["wind_from_deg"])
    base_speed = float(base["wind_speed_kmh"])
    if req.get("wind_rotation_delta_deg") is not None:
        scenario_from = (base_from + float(req["wind_rotation_delta_deg"])) % 360.0
    else:
        scenario_from = base_from
    if req.get("wind_speed_factor") is not None:
        scenario_speed = base_speed * float(req["wind_speed_factor"])
    else:
        scenario_speed = base_speed
    return {
        "wind_from_deg": round(scenario_from, 2),
        "wind_speed_kmh": round(min(scenario_speed, _MAX_WIND_SPEED_KMH), 2),
    }


def _demand_ha_h(area_ha: float, horizon_minutes: int) -> float:
    """Average area growth of the cumulative polygon, normalised to ha/hour."""
    if horizon_minutes <= 0:
        return 0.0
    return round(area_ha / float(horizon_minutes) * 60.0, 3)


def _summarize_side(result: dict[str, Any]) -> dict[str, Any]:
    """Reduce one predict_spread output to the what-if metrics the panel needs."""
    forecasts = result.get("forecasts") or []
    per_horizon = [
        {
            "horizon_minutes": int(item["horizon_minutes"]),
            "area_ha": round(float(item["area_ha"]), 3),
            "demand_ha_h": _demand_ha_h(
                float(item["area_ha"]), int(item["horizon_minutes"])
            ),
        }
        for item in forecasts
    ]
    peak = max(per_horizon, key=lambda row: row["horizon_minutes"], default=None)
    return {
        "spread_direction_deg": round(
            float(result.get("spread_direction_deg") or 0.0), 1
        ),
        "max_horizon_minutes": peak["horizon_minutes"] if peak else 0,
        "area_ha": peak["area_ha"] if peak else 0.0,
        "demand_ha_h": peak["demand_ha_h"] if peak else 0.0,
        "per_horizon": per_horizon,
        "forecasts": [
            {
                "horizon_minutes": int(item["horizon_minutes"]),
                "area_ha": round(float(item["area_ha"]), 3),
                "head_distance_m": round(float(item["head_distance_m"]), 1),
                "spread_direction_deg": round(
                    float(item["spread_direction_deg"] or 0.0), 1
                ),
                "polygon_geojson": item["polygon_geojson"],
            }
            for item in forecasts
        ],
    }


def _forecast_rows(
    result: dict[str, Any], group_key: str
) -> dict[tuple[str, int], Any]:
    """Build ephemeral (un-added, un-committed) forecast rows for exposure."""
    lat = float(result["latitude"])
    lon = float(result["longitude"])
    model_name = str(result.get("model_name") or "rothermel_v1")
    started = utc_now()
    rows: dict[tuple[str, int], Any] = {}
    for item in result.get("forecasts") or []:
        horizon = int(item["horizon_minutes"])
        rows[(group_key, horizon)] = FireForecast(
            event_key=group_key,
            model_name=model_name,
            latitude=lat,
            longitude=lon,
            predicted_area_ha=float(item["area_ha"]),
            geometry_wkt=item.get("geometry_wkt") or "POLYGON(EMPTY)",
            forecast_for=started + timedelta(minutes=horizon),
            horizon_minutes=horizon,
            rate_of_spread_m_per_min=float(item["rate_of_spread_m_min"]),
            spread_direction_deg=float(item["spread_direction_deg"] or 0.0),
            inputs_json="{}",
        )
    return rows


def _threatened_assets(
    session: Session, settings: Any, rows: dict[tuple[str, int], Any]
) -> list[dict[str, Any]]:
    """Rank assets threatened by one ephemeral forecast set (reuses EM-023)."""
    grouped = _polygons_from_rows(rows)
    if not grouped:
        return []
    bbox = _grouped_bbox(grouped)
    max_horizon = max(
        (poly.horizon for polys in grouped.values() for poly in polys),
        default=_DEFAULT_MAX_HORIZON,
    )
    pop_ref = float(getattr(settings, "EXPOSURE_POPULATION_REFERENCE", 100000))
    threatened: list[dict[str, Any]] = []
    for candidate in _candidate_elements(session, bbox):
        shape = _load_shape(candidate["geometry_wkt"])
        if shape is None:
            continue
        impact = _first_impact(shape, grouped)
        if impact is None:
            continue
        item: dict[str, Any] = {
            "asset_key": candidate["asset_key"],
            "asset_type": candidate["asset_type"],
            "name": candidate["name"],
            "population": candidate["population"],
            "event_key": impact["event_key"],
            "first_impact_minutes": impact["est"],
            "impact_horizon_minutes": impact["horizon"],
        }
        item["priority_score"] = _priority_score(item, max_horizon, pop_ref)
        threatened.append(item)
    threatened.sort(
        key=lambda row: (
            -row["priority_score"],
            row["first_impact_minutes"],
            row["asset_type"],
            row["name"] or "",
        )
    )
    return threatened


def _recommendation_view(threatened: list[dict[str, Any]]) -> dict[str, Any]:
    """Commander-facing summary of one side's threat ranking."""
    horizons = [row["first_impact_minutes"] for row in threatened]
    return {
        "count": len(threatened),
        "earliest_impact_minutes": min(horizons) if horizons else None,
        "items": threatened[:10],
    }


def _recommendation_delta(
    original: list[dict[str, Any]], scenario: list[dict[str, Any]]
) -> dict[str, Any]:
    """What the wind change adds to / removes from the threatened set."""
    orig_keys = {row["asset_key"] for row in original}
    scen_keys = {row["asset_key"] for row in scenario}
    orig_earliest = min((row["first_impact_minutes"] for row in original), default=None)
    scen_earliest = min((row["first_impact_minutes"] for row in scenario), default=None)
    newly = [row for row in scenario if row["asset_key"] not in orig_keys]
    cleared = [
        {
            "asset_key": row["asset_key"],
            "name": row["name"],
            "asset_type": row["asset_type"],
        }
        for row in original
        if row["asset_key"] not in scen_keys
    ]
    return {
        "threatened_count_delta": len(scenario) - len(original),
        "earliest_impact_delta_min": (
            scen_earliest - orig_earliest
            if orig_earliest is not None and scen_earliest is not None
            else None
        ),
        "newly_threatened": [
            {
                "asset_key": row["asset_key"],
                "name": row["name"],
                "asset_type": row["asset_type"],
                "first_impact_minutes": row["first_impact_minutes"],
            }
            for row in newly[:10]
        ],
        "no_longer_threatened": cleared[:10],
    }


def _capacity_block(
    effective: dict[str, Any],
    original: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Capacity gap in EM-028's ha/hour unit for both sides plus the delta."""
    capacity = float(effective["total_effective_ha_per_hour"])

    def _side(side: dict[str, Any]) -> dict[str, Any]:
        demand = float(side["demand_ha_h"])
        gap = round(demand - capacity, 3)
        coverage = round(capacity / demand * 100.0, 1) if demand > 0 else None
        return {"demand_ha_h": demand, "gap_ha_h": gap, "coverage_pct": coverage}

    original_side = _side(original)
    scenario_side = _side(scenario)
    return {
        "unit": effective["unit"],
        "effective_ha_h": capacity,
        "effective_by_type": effective["by_type"],
        "original": original_side,
        "scenario": scenario_side,
        "gap_delta_ha_h": round(
            scenario_side["gap_ha_h"] - original_side["gap_ha_h"], 3
        ),
    }


def run_whatif(session: Session, settings: Any, req: dict[str, Any]) -> dict[str, Any]:
    """Recompute risk zones, capacity gap and recommendations for a wind change.

    Deterministic and ephemeral: the engine runs twice on the same resolved
    inputs (unperturbed vs the operator's wind) and nothing is persisted, so
    the original and the scenario are always directly comparable.
    """
    started = perf_counter()
    _validate_wind(req)
    lat = _require_coordinate(req, "latitude")
    lon = _require_coordinate(req, "longitude")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise WhatIfError(f"coordinate out of range: {lat}, {lon}")
    req = dict(req, latitude=lat, longitude=lon)
    group_key = str(req.get("event_key") or "whatif")

    original = predict_spread(session, settings, _predict_request(req))
    base_wind = original["inputs"]
    scenario_wind = _resolve_scenario_wind(base_wind, req)
    scenario = predict_spread(session, settings, _predict_request(req, scenario_wind))

    original_summary = _summarize_side(original)
    scenario_summary = _summarize_side(scenario)
    effective = effective_capacity(session, settings)
    original_threats = _threatened_assets(
        session, settings, _forecast_rows(original, group_key)
    )
    scenario_threats = _threatened_assets(
        session, settings, _forecast_rows(scenario, group_key)
    )

    compute_ms = round((perf_counter() - started) * 1000.0, 1)
    target = recompute_target_seconds(settings)
    return {
        "whatif": WHATIF_MODEL_NAME,
        "generated_at": to_utc_iso(utc_now()),
        "location": {
            "latitude": lat,
            "longitude": lon,
            "event_key": req.get("event_key"),
        },
        "wind": {
            "original": {
                "from_deg": round(float(base_wind["wind_from_deg"]), 2),
                "speed_kmh": round(float(base_wind["wind_speed_kmh"]), 2),
            },
            "scenario": {
                "from_deg": scenario_wind["wind_from_deg"],
                "speed_kmh": scenario_wind["wind_speed_kmh"],
            },
            "rotation_delta_deg": req.get("wind_rotation_delta_deg"),
            "speed_factor": req.get("wind_speed_factor"),
        },
        "original": original_summary,
        "scenario": scenario_summary,
        "capacity": _capacity_block(effective, original_summary, scenario_summary),
        "recommendations": {
            "original": _recommendation_view(original_threats),
            "scenario": _recommendation_view(scenario_threats),
            "delta": _recommendation_delta(original_threats, scenario_threats),
        },
        "model_name": original.get("model_name"),
        "compute_ms": compute_ms,
        "target_seconds": target,
        "within_target": compute_ms <= target * 1000.0,
        "persistence": WHATIF_PERSISTENCE,
        "attribution": WHATIF_ATTRIBUTION,
    }
