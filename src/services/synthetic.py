"""Deterministic synthetic scenario generator for demo use (EM-104).

The demo server needs realistic stand-ins for data that cannot be reached in a
disconnected environment (communication outages, suppression capacity, weather
history). This service builds fully reproducible scenario datasets from a
``seed`` plus a configurable scenario (fire location, wind history, outage
zones, resource distribution).

Guarantees:
* **Same seed, same result** — every value is drawn from a seed-derived
  ``random.Random`` and rounded before emission, so re-running a
  (seed, config) pair yields a byte-identical dataset and ``result_hash``.
* **Explicit labelling** — every synthetic record carries
  ``synthetic: True``, a ``synthetic_source`` and a ``synthetic_label``;
  persisted rows repeat the label in their free-text fields and use ``SYN-``
  prefixed keys. ``ScenarioRun`` stores the seed, canonical config/result
  hashes for the audit trail.
"""
import copy
import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase
from src.models.spatial import FireEvent, SilentRegion
from src.models.synthetic import ScenarioRun
from src.models.weather import WeatherDataPoint
from src.utils.timeutils import utc_now

SYNTHETIC_SOURCE = "EmberMind synthetic scenario generator"
SYNTHETIC_VERSION = "EM-104 v1"
SYNTHETIC_LABEL = "SENTETİK VERİ — demo amaçlı üretildi, gerçek gözlem değildir"
GENERATOR_NAME = f"{SYNTHETIC_SOURCE} ({SYNTHETIC_VERSION})"

# Demo pilot area (Ege/Akdeniz transition, consistent with earlier demos).
DEMO_BBOX = {"min_lat": 36.5, "max_lat": 39.5, "min_lon": 27.0, "max_lon": 29.0}

DEFAULT_CONFIG: dict[str, Any] = {
    "scenario_name": "sentetik-v1",
    "bbox": dict(DEMO_BBOX),
    "fire_location": {"latitude": None, "longitude": None, "severity": None},
    "wind_history": {
        "hours": 24,
        "step_minutes": 60,
        "base_speed_kmh": 18.0,
        "speed_jitter_kmh": 6.0,
        "base_from_deg": 225.0,
        "direction_jitter_deg": 20.0,
        "base_temp_c": 31.0,
        "base_humidity_pct": 25.0,
    },
    "outage_zones": {
        "count": 3,
        "half_span_deg": 0.2,
        "reasons": [
            "iletişim kesintisi (baz istasyonu bakımı)",
            "radyo link kaybısı (yoğun duman)",
            "gsm şebekesi erişilemez (kablo hasarı)",
        ],
    },
    "resource_distribution": {
        "counts": {"crew": 6, "helicopter": 3, "uav": 4},
        "status_weights": {
            "available": 0.5,
            "deployed": 0.3,
            "maintenance": 0.15,
            "out_of_service": 0.05,
        },
        "capacity_ranges": {
            "crew": (15, 40),
            "helicopter": (8, 16),
            "uav": (2, 8),
        },
        "capacity_units": {
            "crew": "personnel",
            "helicopter": "tons",
            "uav": "flight hours",
        },
        "base_count": 2,
    },
}

# Ready-made, nameable scenario variants for the demo server.
PRESETS: dict[str, dict[str, Any]] = {
    "standart": {
        "scenario_name": "sentetik-standart",
    },
    "firtina": {
        "scenario_name": "sentetik-firtina",
        "wind_history": {
            "hours": 24,
            "step_minutes": 60,
            "base_speed_kmh": 48.0,
            "speed_jitter_kmh": 12.0,
            "base_from_deg": 45.0,
            "direction_jitter_deg": 30.0,
            "base_temp_c": 36.0,
            "base_humidity_pct": 12.0,
        },
        "outage_zones": {
            "count": 5,
            "half_span_deg": 0.2,
            "reasons": [
                "iletişim kesintisi (fırtına hat arızası)",
                "radyo link kaybısı (yoğun duman)",
                "gsm şebekesi erişilemez (kablo hasarı)",
            ],
        },
    },
    "kaynak-dagitik": {
        "scenario_name": "sentetik-kaynak-dagitik",
        "resource_distribution": {
            "counts": {"crew": 10, "helicopter": 5, "uav": 6},
            "status_weights": {
                "available": 0.4,
                "deployed": 0.45,
                "maintenance": 0.1,
                "out_of_service": 0.05,
            },
            "capacity_ranges": {
                "crew": (15, 40),
                "helicopter": (8, 16),
                "uav": (2, 8),
            },
            "capacity_units": {
                "crew": "personnel",
                "helicopter": "tons",
                "uav": "flight hours",
            },
            "base_count": 3,
        },
    },
}


class SyntheticError(RuntimeError):
    """Raised for invalid scenario configs, seeds or run keys."""


# --------------------------------------------------------------- helpers ---


class _Rng:
    """Seed-derived deterministic stream (sha256 -> Mersenne Twister)."""

    def __init__(self, seed: int) -> None:
        digest = hashlib.sha256(str(int(seed)).encode("utf-8")).digest()
        self._random = random.Random(int.from_bytes(digest, "big"))

    def uniform(self, low: float, high: float) -> float:
        return self._random.uniform(low, high)

    def gauss(self, mu: float, sigma: float) -> float:
        return self._random.gauss(mu, sigma)

    def choice(self, seq: list[str]) -> str:
        return self._random.choice(seq)

    def weighted(self, weights: dict[str, float]) -> str:
        keys = sorted(weights)
        return self._random.choices(keys, weights=[weights[k] for k in keys])[0]


def canonical_json(value: Any) -> str:
    """Stable JSON encoding used for hashing (sorted keys, no whitespace)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_of(value: Any) -> str:
    """sha256 hex digest of the canonical JSON form of ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _iso_z(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _require_finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SyntheticError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise SyntheticError(f"{field} must be finite")
    return number


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_config(
    config: dict[str, Any] | None, preset: str | None = None
) -> dict[str, Any]:
    """Merge defaults + preset + overrides, then validate the scenario."""
    # Deep copy: validation below writes into nested blocks (fire_location,
    # wind, resource_distribution...); a shallow dict() would mutate the
    # module-level DEFAULT_CONFIG and corrupt every later request.
    merged = copy.deepcopy(DEFAULT_CONFIG)
    if preset:
        preset_key = str(preset).strip().lower()
        if preset_key not in PRESETS:
            raise SyntheticError(
                f"unknown preset '{preset}'; available: {sorted(PRESETS)}"
            )
        merged = _merge_config(merged, PRESETS[preset_key])
    if config:
        merged = _merge_config(merged, dict(config))

    bbox = merged["bbox"]
    min_lat = _require_finite(bbox.get("min_lat"), "bbox.min_lat")
    max_lat = _require_finite(bbox.get("max_lat"), "bbox.max_lat")
    min_lon = _require_finite(bbox.get("min_lon"), "bbox.min_lon")
    max_lon = _require_finite(bbox.get("max_lon"), "bbox.max_lon")
    if not min_lat < max_lat or not min_lon < max_lon:
        raise SyntheticError("bbox must satisfy min_lat < max_lat, min_lon < max_lon")
    if not -90 <= min_lat or max_lat > 90 or abs(min_lon) > 180 or abs(max_lon) > 180:
        raise SyntheticError("bbox outside coordinate ranges")

    fire = merged["fire_location"]
    lat, lon = fire.get("latitude"), fire.get("longitude")
    if lat is not None:
        lat = _require_finite(lat, "fire_location.latitude")
        if not min_lat <= lat <= max_lat:
            raise SyntheticError("fire_location.latitude outside bbox")
    if lon is not None:
        lon = _require_finite(lon, "fire_location.longitude")
        if not min_lon <= lon <= max_lon:
            raise SyntheticError("fire_location.longitude outside bbox")
    fire["latitude"] = round(lat, 6) if lat is not None else None
    fire["longitude"] = round(lon, 6) if lon is not None else None

    wind = merged["wind_history"]
    hours = int(wind.get("hours", 0))
    if not 1 <= hours <= 168:
        raise SyntheticError("wind_history.hours must be within [1, 168]")
    wind["hours"] = hours
    steps = int(wind.get("step_minutes", 0))
    if steps not in (15, 30, 60):
        raise SyntheticError("wind_history.step_minutes must be 15, 30 or 60")
    wind["step_minutes"] = steps
    if _require_finite(wind["base_speed_kmh"], "base_speed_kmh") < 0:
        raise SyntheticError("wind_history.base_speed_kmh must be >= 0")

    outage = merged["outage_zones"]
    count = int(outage.get("count", -1))
    if not 0 <= count <= 20:
        raise SyntheticError("outage_zones.count must be within [0, 20]")
    outage["count"] = count
    span = _require_finite(outage["half_span_deg"], "half_span_deg")
    if not 0 < span <= 5:
        raise SyntheticError("outage_zones.half_span_deg must be in (0, 5]")
    outage["half_span_deg"] = round(span, 6)
    if not outage.get("reasons"):
        raise SyntheticError("outage_zones.reasons must not be empty")

    res = merged["resource_distribution"]
    counts = res.get("counts") or {}
    unknown = sorted(set(counts) - {"crew", "helicopter", "uav"})
    if unknown:
        raise SyntheticError(f"resource_distribution.counts unknown types: {unknown}")
    for name, value in counts.items():
        if not 0 <= int(value) <= 200:
            raise SyntheticError("resource counts must be within [0, 200]")
        counts[name] = int(value)
    weights = res.get("status_weights") or {}
    if not weights:
        raise SyntheticError("resource_distribution.status_weights must not be empty")
    for name, value in weights.items():
        weights[name] = _require_finite(value, f"status_weights.{name}")
        if weights[name] < 0:
            raise SyntheticError(f"status_weights.{name} must be >= 0")
    if sum(weights.values()) <= 0:
        raise SyntheticError("status_weights must sum to > 0")
    for name, pair in (res.get("capacity_ranges") or {}).items():
        low, high = _require_finite(pair[0], f"capacity_ranges.{name}[0]"), (
            _require_finite(pair[1], f"capacity_ranges.{name}[1]")
        )
        if low > high:
            raise SyntheticError(f"capacity_ranges.{name} must be [low, high]")
        res["capacity_ranges"][name] = [low, high]
    base_count = int(res.get("base_count", 1))
    if not 0 <= base_count <= 20:
        raise SyntheticError("resource_distribution.base_count must be within [0, 20]")
    res["base_count"] = base_count
    return merged


# ------------------------------------------------------------- generator ---


def _labelled(record: dict[str, Any]) -> dict[str, Any]:
    """Attach the mandatory synthetic markers to one record."""
    record["synthetic"] = True
    record["synthetic_source"] = SYNTHETIC_SOURCE
    record["synthetic_version"] = SYNTHETIC_VERSION
    record["synthetic_label"] = SYNTHETIC_LABEL
    return record


def build_dataset(
    seed: int, config: dict[str, Any] | None = None, preset: str | None = None
) -> dict[str, Any]:
    """Generate the deterministic synthetic dataset for (seed, config).

    The same ``seed`` with the same normalized config always returns an
    identical payload; ``meta.result_hash`` is its canonical fingerprint.
    """
    try:
        seed_int = int(seed)
    except (TypeError, ValueError) as exc:
        raise SyntheticError("seed must be an integer") from exc
    cfg = normalize_config(config, preset)
    base_epoch = _require_finite(cfg.get("base_time_epoch", 1725062400), "base_time")
    base_dt = datetime.fromtimestamp(base_epoch, tz=timezone.utc).replace(tzinfo=None)
    rng = _Rng(seed_int)
    bbox = cfg["bbox"]
    scenario_tag = f"syn-{sha256_of(cfg)[:10]}"

    # --- fire location -------------------------------------------------
    fire_cfg = cfg["fire_location"]
    lat = fire_cfg["latitude"]
    lon = fire_cfg["longitude"]
    lat = (
        round(rng.uniform(bbox["min_lat"], bbox["max_lat"]), 6) if lat is None else lat
    )
    lon = (
        round(rng.uniform(bbox["min_lon"], bbox["max_lon"]), 6) if lon is None else lon
    )
    half = 0.05
    fire = _labelled(
        {
            "event_key": f"SYN-{scenario_tag}-FIRE",
            "name": f"Sentetik yangın — {cfg['scenario_name']}",
            "latitude": lat,
            "longitude": lon,
            "min_lat": round(lat - half, 6),
            "max_lat": round(lat + half, 6),
            "min_lon": round(lon - half, 6),
            "max_lon": round(lon + half, 6),
            "geometry_wkt": (
                f"POLYGON(({round(lon - half, 6)} {round(lat - half, 6)},"
                f" {round(lon + half, 6)} {round(lat - half, 6)},"
                f" {round(lon + half, 6)} {round(lat + half, 6)},"
                f" {round(lon - half, 6)} {round(lat + half, 6)},"
                f" {round(lon - half, 6)} {round(lat - half, 6)}))"
            ),
            "severity": fire_cfg.get("severity")
            or rng.choice(["low", "medium", "high", "very_high"]),
            "status": "active",
            "started_at": _iso_z(base_dt),
        }
    )

    # --- wind history (random walk around the fire origin) --------------
    wind_cfg = cfg["wind_history"]
    samples = int(wind_cfg["hours"] * 60 // wind_cfg["step_minutes"]) + 1
    speed = float(wind_cfg["base_speed_kmh"])
    bearing = float(wind_cfg["base_from_deg"])
    temp = float(wind_cfg["base_temp_c"])
    humidity = float(wind_cfg["base_humidity_pct"])
    wind_history: list[dict[str, Any]] = []
    for step in range(samples):
        speed = max(0.0, speed + rng.gauss(0.0, float(wind_cfg["speed_jitter_kmh"])))
        bearing = (
            bearing + rng.gauss(0.0, float(wind_cfg["direction_jitter_deg"]))
        ) % 360.0
        temp = min(45.0, max(-10.0, temp + rng.gauss(0.0, 0.6)))
        humidity = min(95.0, max(5.0, humidity + rng.gauss(0.0, 1.5)))
        wind_history.append(
            _labelled(
                {
                    "t": _iso_z(
                        base_dt
                        + timedelta(minutes=step * int(wind_cfg["step_minutes"]))
                    ),
                    "offset_hours": round(step * wind_cfg["step_minutes"] / 60.0, 2),
                    "latitude": lat,
                    "longitude": lon,
                    "wind_speed_kmh": round(speed, 1),
                    "wind_from_deg": round(bearing, 1),
                    "air_temp_c": round(temp, 1),
                    "relative_humidity_pct": round(humidity, 1),
                    "rain_mm": 0.0,
                }
            )
        )

    # --- communication outage zones -------------------------------------
    outage_cfg = cfg["outage_zones"]
    outage_zones: list[dict[str, Any]] = []
    for index in range(int(outage_cfg["count"])):
        center_lat = round(
            min(
                max(rng.uniform(lat - 0.8, lat + 0.8), bbox["min_lat"]), bbox["max_lat"]
            ),
            6,
        )
        center_lon = round(
            min(
                max(rng.uniform(lon - 0.8, lon + 0.8), bbox["min_lon"]), bbox["max_lon"]
            ),
            6,
        )
        span = float(outage_cfg["half_span_deg"])
        reasons = [str(item) for item in outage_cfg["reasons"]]
        outage_zones.append(
            _labelled(
                {
                    "zone_key": f"SYN-{scenario_tag}-OUT-{index + 1}",
                    "name": f"Sentetik kesinti bölgesi {index + 1} [{scenario_tag}]",
                    "reason": rng.choice(reasons),
                    "center_lat": center_lat,
                    "center_lon": center_lon,
                    "min_lat": round(center_lat - span, 6),
                    "max_lat": round(center_lat + span, 6),
                    "min_lon": round(center_lon - span, 6),
                    "max_lon": round(center_lon + span, 6),
                    "geometry_wkt": (
                        f"POLYGON(({round(center_lon - span, 6)} {round(center_lat - span, 6)},"
                        f" {round(center_lon + span, 6)} {round(center_lat - span, 6)},"
                        f" {round(center_lon + span, 6)} {round(center_lat + span, 6)},"
                        f" {round(center_lon - span, 6)} {round(center_lat + span, 6)},"
                        f" {round(center_lon - span, 6)} {round(center_lat - span, 6)}))"
                    ),
                    "is_active": True,
                }
            )
        )

    # --- resource distribution (bases + deployable assets) ---------------
    res_cfg = cfg["resource_distribution"]
    bases: list[dict[str, Any]] = []
    for index in range(int(res_cfg["base_count"])):
        base_lat = round(rng.uniform(bbox["min_lat"], bbox["max_lat"]), 6)
        base_lon = round(rng.uniform(bbox["min_lon"], bbox["max_lon"]), 6)
        bases.append(
            _labelled(
                {
                    "base_key": f"SYN-{scenario_tag}-BASE-{index + 1}",
                    "name": f"Sentetik üs {index + 1}",
                    "latitude": base_lat,
                    "longitude": base_lon,
                    "crew_type": "first_response",
                    "available": True,
                }
            )
        )
    type_abbr = {"crew": "EKIP", "helicopter": "HELI", "uav": "IHA"}
    resources: list[dict[str, Any]] = []
    seq = 0
    weights = {str(k): float(v) for k, v in res_cfg["status_weights"].items()}
    for rtype in sorted(res_cfg["counts"]):
        ranges = res_cfg.get("capacity_ranges") or {}
        units = res_cfg.get("capacity_units") or {}
        low, high = (
            (float(ranges[rtype][0]), float(ranges[rtype][1]))
            if rtype in ranges
            else (0.0, 0.0)
        )
        for _ in range(int(res_cfg["counts"][rtype])):
            seq += 1
            home = (
                bases[seq % len(bases)]
                if bases
                else {"latitude": lat, "longitude": lon}
            )
            resources.append(
                _labelled(
                    {
                        "resource_key": f"SYN-{scenario_tag}-{type_abbr.get(rtype, 'KAY')}-{seq:02d}",
                        "name": f"Sentetik {rtype} #{seq}",
                        "resource_type": rtype,
                        "latitude": round(
                            min(
                                max(rng.gauss(home["latitude"], 0.15), bbox["min_lat"]),
                                bbox["max_lat"],
                            ),
                            6,
                        ),
                        "longitude": round(
                            min(
                                max(
                                    rng.gauss(home["longitude"], 0.15), bbox["min_lon"]
                                ),
                                bbox["max_lon"],
                            ),
                            6,
                        ),
                        "base_key": home.get("base_key"),
                        "country": "TR",
                        "status": rng.weighted(weights),
                        "capacity": round(rng.uniform(low, high), 1),
                        "capacity_unit": str(units.get(rtype, "")) or None,
                    }
                )
            )

    record_count = (
        1 + len(wind_history) + len(outage_zones) + len(bases) + len(resources)
    )
    meta: dict[str, Any] = {
        "generator": GENERATOR_NAME,
        "scenario_tag": scenario_tag,
        "scenario_name": str(cfg["scenario_name"]),
        "seed": seed_int,
        "base_time": _iso_z(base_dt),
        "base_time_epoch": base_epoch,
        "record_count": record_count,
        "synthetic": True,
        "synthetic_source": SYNTHETIC_SOURCE,
        "synthetic_version": SYNTHETIC_VERSION,
        "synthetic_label": SYNTHETIC_LABEL,
        "notice": "Tüm alanlar sentetiktir; operasyonel kararlarda kullanılmaz.",
        "config_hash": sha256_of(cfg),
    }
    dataset: dict[str, Any] = {
        "fire": fire,
        "wind_history": wind_history,
        "outage_zones": outage_zones,
        "resource_distribution": {"bases": bases, "resources": resources},
        "meta": meta,
    }
    # The fingerprint covers the dataset only; the config hash rides along in
    # ``meta`` and is injected *after* hashing so it stays reproducible.
    dataset["meta"]["result_hash"] = sha256_of(dataset)
    dataset["config"] = cfg
    return dataset


# ----------------------------------------------------------- persistence ---


def _persist_fire(session: Session, record: dict[str, Any]) -> None:
    event = session.scalar(
        select(FireEvent).where(FireEvent.event_key == record["event_key"])
    )
    if event is None:
        event = FireEvent(event_key=record["event_key"])
        session.add(event)
    event.name = record["name"]  # type: ignore[assignment]
    event.latitude = record["latitude"]  # type: ignore[assignment]
    event.longitude = record["longitude"]  # type: ignore[assignment]
    event.min_lat = record["min_lat"]  # type: ignore[assignment]
    event.max_lat = record["max_lat"]  # type: ignore[assignment]
    event.min_lon = record["min_lon"]  # type: ignore[assignment]
    event.max_lon = record["max_lon"]  # type: ignore[assignment]
    event.geometry_wkt = record["geometry_wkt"]  # type: ignore[assignment]
    event.severity = record["severity"]  # type: ignore[assignment]
    event.status = record["status"]  # type: ignore[assignment]
    event.started_at = datetime.fromisoformat(str(record["started_at"]).replace("Z", "+00:00")).replace(tzinfo=None)  # type: ignore[assignment]
    event.source = "synthetic"  # type: ignore[assignment]
    event.notes = record["synthetic_label"]  # type: ignore[assignment]
    event.reported_by = SYNTHETIC_SOURCE  # type: ignore[assignment]


def _persist_outages(session: Session, records: list[dict[str, Any]]) -> None:
    for record in records:
        # Upsert by name so re-seeding the same scenario stays idempotent.
        region = session.scalar(
            select(SilentRegion).where(SilentRegion.region_name == record["name"])
        )
        if region is None:
            region = SilentRegion(region_name=record["name"])
            session.add(region)
        region.reason = f"{record['reason']} — {record['synthetic_label']}"  # type: ignore[assignment]
        region.min_lat = record["min_lat"]  # type: ignore[assignment]
        region.max_lat = record["max_lat"]  # type: ignore[assignment]
        region.min_lon = record["min_lon"]  # type: ignore[assignment]
        region.max_lon = record["max_lon"]  # type: ignore[assignment]
        region.geometry_wkt = record["geometry_wkt"]  # type: ignore[assignment]
        region.is_active = True  # type: ignore[assignment]


def _persist_wind(
    session: Session, records: list[dict[str, Any]], fire_key: str
) -> None:
    # Synthetic wind-history rows share one cluster key derived from the fire;
    # existing rows for that cluster are replaced so re-seeding is idempotent.
    cluster_key = fire_key.replace("-FIRE", "-WIND")
    session.execute(
        delete(WeatherDataPoint).where(
            WeatherDataPoint.cluster_key == cluster_key  # type: ignore[attr-defined]
        )
    )
    for record in records:
        session.add(
            WeatherDataPoint(
                cluster_key=cluster_key,
                latitude=record["latitude"],
                longitude=record["longitude"],
                temperature=record["air_temp_c"],
                humidity=record["relative_humidity_pct"],
                wind_speed=record["wind_speed_kmh"],
                wind_deg=record["wind_from_deg"],
                rain=record["rain_mm"],
                forecast_offset_hours=0,
                forecast_time=datetime.fromisoformat(
                    str(record["t"]).replace("Z", "+00:00")
                ).replace(tzinfo=None),
                fetched_at=utc_now(),
                source="synthetic (EM-104)",
            )
        )


def _persist_resources(session: Session, block: dict[str, Any]) -> None:
    for record in block.get("bases", []):
        exists = session.scalar(
            select(CrewBase).where(CrewBase.base_key == record["base_key"])
        )
        if exists is None:
            session.add(
                CrewBase(
                    base_key=record["base_key"],
                    name=f"{record['name']} (sentetik)",
                    latitude=record["latitude"],
                    longitude=record["longitude"],
                    crew_type=record["crew_type"],
                    available=bool(record["available"]),
                )
            )
    for record in block.get("resources", []):
        exists = session.scalar(
            select(SuppressionResource).where(
                SuppressionResource.resource_key == record["resource_key"]
            )
        )
        if exists is None:
            session.add(
                SuppressionResource(
                    resource_key=record["resource_key"],
                    name=record["name"],
                    resource_type=record["resource_type"],
                    latitude=record["latitude"],
                    longitude=record["longitude"],
                    base_key=record["base_key"],
                    country=record["country"],
                    status=record["status"],
                    capacity=float(record["capacity"]),
                    capacity_unit=record["capacity_unit"],
                )
            )


def persist_dataset(session: Session, dataset: dict[str, Any]) -> dict[str, int]:
    """Write a generated dataset into the operational tables (labelled)."""
    counts = {"events": 1, "silent_regions": 0, "weather_points": 0, "resources": 0}
    _persist_fire(session, dataset["fire"])
    _persist_outages(session, dataset["outage_zones"])
    counts["silent_regions"] = len(dataset["outage_zones"])
    _persist_wind(session, dataset["wind_history"], str(dataset["fire"]["event_key"]))
    counts["weather_points"] = len(dataset["wind_history"])
    block = dataset["resource_distribution"]
    _persist_resources(session, block)
    counts["resources"] = len(block.get("bases", [])) + len(block.get("resources", []))
    session.flush()
    return counts


def cleanup_scenario(session: Session, scenario_tag: str) -> dict[str, int]:
    """Delete persisted synthetic rows for one scenario tag."""
    tag = str(scenario_tag).strip()
    if not tag.startswith("syn-"):
        raise SyntheticError("scenario_tag must start with 'syn-'")
    # LIKE wildcards in the tag would widen the DELETE to other scenarios
    # (a bare '%' would wipe every synthetic row) — escape them literally.
    escaped = tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    deleted: dict[str, int] = {}
    deleted["fire_events"] = session.execute(
        delete(FireEvent).where(
            FireEvent.event_key.like(like, escape="\\")  # type: ignore[attr-defined]
        )
    ).rowcount
    deleted["silent_regions"] = session.execute(
        delete(SilentRegion).where(
            SilentRegion.region_name.like(like, escape="\\")  # type: ignore[attr-defined]
        )
    ).rowcount
    deleted["weather_points"] = session.execute(
        delete(WeatherDataPoint).where(
            WeatherDataPoint.cluster_key.like(like, escape="\\")  # type: ignore[attr-defined]
        )
    ).rowcount
    deleted["crew_bases"] = session.execute(
        delete(CrewBase).where(
            CrewBase.base_key.like(like, escape="\\")  # type: ignore[attr-defined]
        )
    ).rowcount
    deleted["suppression_resources"] = session.execute(
        delete(SuppressionResource).where(
            SuppressionResource.resource_key.like(like, escape="\\")  # type: ignore[attr-defined]
        )
    ).rowcount
    session.flush()
    return deleted


# ---------------------------------------------------------------- runs ----


def record_run(
    session: Session,
    dataset: dict[str, Any],
    persisted: bool,
    preset: str | None = None,
) -> ScenarioRun:
    """Store the audit-trail row for one generation run."""
    meta = dataset["meta"]
    seed = int(meta["seed"])
    run_key = f"synrun-{meta['result_hash'][:16]}"
    existing = session.scalar(select(ScenarioRun).where(ScenarioRun.run_key == run_key))
    if existing is not None:
        if persisted and not existing.persisted:
            existing.persisted = 1  # type: ignore[assignment]
            session.flush()
        return existing
    run = ScenarioRun(
        run_key=run_key,
        scenario_tag=str(meta["scenario_tag"]),
        seed=seed,
        preset=preset,
        config_hash=str(meta["config_hash"]),
        result_hash=str(meta["result_hash"]),
        base_time=_require_finite(meta.get("base_time_epoch", 1725062400), "base_time"),
        record_count=int(meta["record_count"]),
        persisted=1 if persisted else 0,
        config_json=canonical_json(dataset.get("config", {})),
        dataset_json=canonical_json(
            {k: v for k, v in dataset.items() if k != "config"}
        ),
        generated_at=utc_now(),
    )
    session.add(run)
    session.flush()
    return run


def list_runs(session: Session, limit: int = 50) -> list[ScenarioRun]:
    """Recent generation runs, newest first."""
    query = (
        select(ScenarioRun).order_by(ScenarioRun.generated_at.desc()).limit(int(limit))
    )
    return list(session.scalars(query))


def get_run(session: Session, run_key: str) -> ScenarioRun | None:
    """Fetch one generation run by key."""
    return session.scalar(select(ScenarioRun).where(ScenarioRun.run_key == run_key))
