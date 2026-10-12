"""Ready-made demo scenario library (EM-105, Epic E11).

The demo host wants to launch a *named* scenario with a single click and be able
to rewind it, so a presentation always starts from the same reproducible state.
EM-104 shipped the raw deterministic generator (seed + config -> labelled
dataset); EM-105 curates a small library of archetypal scenarios on top of it:

* ``kiyi-ruzgar-donusu`` — a coastal fire with a strongly veering wind (the walk
  swings wide enough to read as a wind reversal over the sea front);
* ``kirsal-sessiz-bolge`` — an inland rural fire wrapped in communication
  outage / silent zones with thin local resources;
* ``sinir-bolgesi`` — a fast-moving fire anchored on the notional cross-border
  line (its longitude is a configuration knob, see ``SCENARIO_BORDER_LON``).

Every entry is a *fixed* ``(seed, config)`` pair fed through the EM-104 engine,
so activation is fully deterministic: the same scenario always yields the same
``scenario_tag`` and ``result_hash``. "Replay" (rewind) therefore means tearing
down the persisted rows for that tag and re-seeding the identical dataset, which
returns the demo to the exact same starting state. The library catalog itself is
a code constant (like EM-104 ``PRESETS``); the only persisted artefacts are the
operational rows written by EM-104 and one ``ScenarioRun`` audit row per launch
(the run's ``preset`` column is stamped ``library:<key>`` so library activations
are identifiable). No new table / migration is required.
"""
import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.synthetic import ScenarioRun
from src.services.synthetic import (
    DEMO_BBOX,
    SYNTHETIC_LABEL,
    SyntheticError,
    build_dataset,
    cleanup_scenario,
    persist_dataset,
    record_run,
)

LIBRARY_VERSION = "EM-105 v1"
LIBRARY_PERSISTENCE = "reuses EM-104 synthetic rows + ScenarioRun (no new table)"
ATTRIBUTION = (
    "Hazır demo senaryoları: EmberMind senaryo kütüphanesi (EM-105) — EM-104 "
    "üreteci üzerinde sabit (seed, config); gerçek gözlem değildir"
)
PRESET_PREFIX = "library:"

# The notional cross-border line for the ``sinir-bolgesi`` scenario, clamped to
# sit just inside the demo bbox so a misconfigured env value cannot invalidate it.
DEFAULT_BORDER_LON = 28.85
_BORDER_MARGIN = 0.02


class ScenarioLibraryError(SyntheticError):
    """Raised for an unknown library key or an out-of-range border setting."""


# Curated archetypes. ``config`` is a partial override merged over the EM-104
# DEFAULT_CONFIG by build_dataset; ``border_anchored`` scenarios pull their fire
# longitude from SCENARIO_BORDER_LON at activation time.
LIBRARY: list[dict[str, Any]] = [
    {
        "key": "kiyi-ruzgar-donusu",
        "title": "Kıyı yangını + rüzgâr dönüşü",
        "description": (
            "Ege kıyısında yüksek şiddetli bir yangın; rüzgâr geniş açıyla "
            "salındığı için yön değiştirme (rüzgâr dönüşü) riski öne çıkar."
        ),
        "archetype": "coastal_wind_reversal",
        "seed": 101,
        "config": {
            "scenario_name": "library-kiyi-ruzgar-donusu",
            "fire_location": {
                "latitude": 37.9,
                "longitude": 27.25,
                "severity": "high",
            },
            "wind_history": {
                "hours": 12,
                "step_minutes": 60,
                "base_speed_kmh": 30.0,
                "speed_jitter_kmh": 10.0,
                "base_from_deg": 300.0,
                "direction_jitter_deg": 85.0,
                "base_temp_c": 34.0,
                "base_humidity_pct": 16.0,
            },
            "outage_zones": {"count": 1},
        },
    },
    {
        "key": "kirsal-sessiz-bolge",
        "title": "Sessiz bölge içeren kırsal yangın",
        "description": (
            "İç kesimde orta şiddetli kırsal yangın; iletişim kesintisi / sessiz "
            "bölgelerle çevrili ve yerel kaynak sayısı düşük."
        ),
        "archetype": "rural_silent_zone",
        "seed": 202,
        "config": {
            "scenario_name": "library-kirsal-sessiz-bolge",
            "fire_location": {
                "latitude": 37.35,
                "longitude": 28.6,
                "severity": "medium",
            },
            "wind_history": {
                "hours": 12,
                "step_minutes": 60,
                "base_speed_kmh": 20.0,
                "direction_jitter_deg": 15.0,
            },
            "outage_zones": {
                "count": 3,
                "half_span_deg": 0.25,
                "reasons": [
                    "iletişim kesintisi (kırsal baz istasyonu yok)",
                    "radyo link kaybısı (dağ vadi)",
                    "gsm şebekesi erişilemez (kırsal bölge)",
                ],
            },
            "resource_distribution": {
                "counts": {"crew": 2, "helicopter": 1, "uav": 0},
                "base_count": 1,
            },
        },
    },
    {
        "key": "sinir-bolgesi",
        "title": "Sınır bölgesi yangını",
        "description": (
            "Notional sınır hattı üzerinde çok yüksek şiddetli, hızlı ilerleyen "
            "bir yangın; sınır ötesi yayılım senaryosu için hazır."
        ),
        "archetype": "border_region",
        "seed": 303,
        "border_anchored": True,
        "config": {
            "scenario_name": "library-sinir-bolgesi",
            "fire_location": {
                "latitude": 38.6,
                "longitude": None,  # filled from SCENARIO_BORDER_LON
                "severity": "very_high",
            },
            "wind_history": {
                "hours": 12,
                "step_minutes": 60,
                "base_speed_kmh": 26.0,
                "base_from_deg": 90.0,
                "direction_jitter_deg": 40.0,
            },
            "outage_zones": {"count": 1},
            "resource_distribution": {
                "counts": {"crew": 4, "helicopter": 2, "uav": 1},
                "base_count": 2,
            },
        },
    },
]

_SCENARIOS_BY_KEY: dict[str, dict[str, Any]] = {str(s["key"]): s for s in LIBRARY}
LIBRARY_KEYS: tuple[str, ...] = tuple(_SCENARIOS_BY_KEY)


# --------------------------------------------------------------- catalog ---


def catalog() -> list[dict[str, Any]]:
    """The library scenarios as lightweight summaries (no dataset build)."""
    return [
        {
            "key": str(item["key"]),
            "title": str(item["title"]),
            "description": str(item["description"]),
            "archetype": str(item["archetype"]),
            "seed": int(item["seed"]),
        }
        for item in LIBRARY
    ]


def get_scenario(key: str) -> dict[str, Any]:
    """Return one curated scenario definition or raise for an unknown key."""
    normalized = str(key).strip().lower()
    scenario = _SCENARIOS_BY_KEY.get(normalized)
    if scenario is None:
        raise ScenarioLibraryError(
            f"unknown scenario key '{key}'; available: {sorted(LIBRARY_KEYS)}"
        )
    return scenario


def _border_lon(settings: Any) -> float:
    """Resolve + clamp the notional border longitude into the demo bbox."""
    raw = getattr(settings, "SCENARIO_BORDER_LON", DEFAULT_BORDER_LON)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioLibraryError("SCENARIO_BORDER_LON must be numeric") from exc
    low = DEMO_BBOX["min_lon"] + _BORDER_MARGIN
    high = DEMO_BBOX["max_lon"] - _BORDER_MARGIN
    return round(min(max(value, low), high), 6)


def materialize_config(scenario: dict[str, Any], settings: Any) -> dict[str, Any]:
    """Deep-copy the scenario config, resolving any settings-driven anchors."""
    cfg = copy.deepcopy(scenario["config"])
    if scenario.get("border_anchored"):
        cfg["fire_location"]["longitude"] = _border_lon(settings)
    return cfg


def preview(key: str, settings: Any) -> dict[str, Any]:
    """Build the scenario dataset (no persistence) and return a light summary."""
    scenario = get_scenario(key)
    cfg = materialize_config(scenario, settings)
    dataset = build_dataset(int(scenario["seed"]), cfg)
    meta = dataset["meta"]
    return {
        "scenario": catalog_entry(key),
        "scenario_tag": str(meta["scenario_tag"]),
        "result_hash": str(meta["result_hash"]),
        "config_hash": str(meta["config_hash"]),
        "record_count": int(meta["record_count"]),
        "fire": dataset["fire"],
        "outage_zone_count": len(dataset["outage_zones"]),
        "synthetic_label": SYNTHETIC_LABEL,
    }


def catalog_entry(key: str) -> dict[str, Any]:
    """The single-scenario summary block (same shape as ``catalog`` rows)."""
    scenario = get_scenario(key)
    return {
        "key": str(scenario["key"]),
        "title": str(scenario["title"]),
        "description": str(scenario["description"]),
        "archetype": str(scenario["archetype"]),
        "seed": int(scenario["seed"]),
    }


# ------------------------------------------------------------- activation ---


def _launch_summary(
    scenario: dict[str, Any], dataset: dict[str, Any], counts: dict[str, int]
) -> dict[str, Any]:
    meta = dataset["meta"]
    return {
        "key": str(scenario["key"]),
        "title": str(scenario["title"]),
        "archetype": str(scenario["archetype"]),
        "scenario_tag": str(meta["scenario_tag"]),
        "result_hash": str(meta["result_hash"]),
        "record_count": int(meta["record_count"]),
        "persisted_counts": counts,
        "synthetic_label": SYNTHETIC_LABEL,
    }


def activate(session: Session, key: str, settings: Any) -> dict[str, Any]:
    """One-click start: generate + persist the scenario, record the run."""
    scenario = get_scenario(key)
    cfg = materialize_config(scenario, settings)
    dataset = build_dataset(int(scenario["seed"]), cfg)
    counts = persist_dataset(session, dataset)
    run = record_run(
        session, dataset, persisted=True, preset=f"{PRESET_PREFIX}{scenario['key']}"
    )
    summary = _launch_summary(scenario, dataset, counts)
    summary["run"] = run.as_dict
    return {"status": "activated", "scenario": summary, "attribution": ATTRIBUTION}


def replay(session: Session, key: str, settings: Any) -> dict[str, Any]:
    """Rewind + relaunch deterministically (same tag/hash every time)."""
    scenario = get_scenario(key)
    cfg = materialize_config(scenario, settings)
    dataset = build_dataset(int(scenario["seed"]), cfg)
    tag = str(dataset["meta"]["scenario_tag"])
    deleted = cleanup_scenario(session, tag)
    counts = persist_dataset(session, dataset)
    run = record_run(
        session, dataset, persisted=True, preset=f"{PRESET_PREFIX}{scenario['key']}"
    )
    summary = _launch_summary(scenario, dataset, counts)
    summary["run"] = run.as_dict
    return {
        "status": "replayed",
        "scenario": summary,
        "rewound": deleted,
        "attribution": ATTRIBUTION,
    }


# ---------------------------------------------------------------- runs ---


def activated_runs(
    session: Session, key: str | None = None, limit: int = 50
) -> list[ScenarioRun]:
    """Recent library activations (optionally filtered to one scenario key)."""
    stmt = select(ScenarioRun).order_by(ScenarioRun.generated_at.desc())
    if key is not None:
        scenario = get_scenario(key)
        stmt = stmt.where(ScenarioRun.preset == f"{PRESET_PREFIX}{scenario['key']}")
    else:
        stmt = stmt.where(ScenarioRun.preset.like(f"{PRESET_PREFIX}%"))  # type: ignore[attr-defined]
    stmt = stmt.limit(int(limit))
    return list(session.scalars(stmt))


def library_config(settings: Any) -> dict[str, Any]:
    """Read-time projection of the library (catalog + launch guarantees)."""
    return {
        "version": LIBRARY_VERSION,
        "scenarios": catalog(),
        "count": len(LIBRARY),
        "border_lon": _border_lon(settings),
        "determinism": "her senaryo sabit (seed, config); aynı etiket + aynı hash",
        "replay": "geri sar = etiketi sil + aynı veriyi yeniden tohumla",
        "persistence": LIBRARY_PERSISTENCE,
        "synthetic_label": SYNTHETIC_LABEL,
        "attribution": ATTRIBUTION,
    }
