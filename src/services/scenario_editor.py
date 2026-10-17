"""UI-authored custom demo scenarios (EM-108, Epic E11).

EM-105 curates a fixed, code-constant library of archetypes. The demo host also
wants to *author* a brand-new scenario from the interface without writing code
(EM-108 acceptance: "fire location, wind history and exclusion zones are entered
through the UI; the scenario is saved and added to the library; input validation
is enforced"). This service is that editor: it validates an authored EM-104
scenario config, persists the definition as a ``CustomScenario`` row and lets the
demo host preview / one-click activate it exactly like a library scenario.

Design choices that keep the feature honest and reproducible:

* **Validation is not re-invented** — the config is pushed through the EM-104
  ``normalize_config`` (which enforces the demo bbox, wind-hour/step bounds,
  outage-zone count/span and resource-count ranges) so a saved scenario is
  guaranteed launchable; on top of that this layer checks the slug key, the
  title, the seed range and a per-installation cap on the number of scenarios.
* **Determinism** — the *normalized* config is stored (canonical JSON), so an
  activation is byte-identical every time and does not drift if ``DEFAULT_CONFIG``
  changes later. The fire location, wind history and exclusion zones authored in
  the UI are exactly the ``fire_location`` / ``wind_history`` / ``outage_zones``
  blocks the generator consumes.
* **Reuse, not duplication** — activation reuses the EM-104
  ``build_dataset``/``persist_dataset``/``record_run`` path and stamps one
  ``ScenarioRun`` audit row with ``preset=custom:<key>`` (mirroring how EM-105
  stamps ``library:<key>``), so custom launches are identifiable in the run log.
"""
import copy
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.scenario_editor import CustomScenario
from src.services.scenario_library import LIBRARY_KEYS
from src.services.synthetic import (
    SYNTHETIC_LABEL,
    SyntheticError,
    build_dataset,
    canonical_json,
    normalize_config,
    persist_dataset,
    record_run,
)

EDITOR_VERSION = "EM-108 v1"
EDITOR_PERSISTENCE = "custom_scenarios (definition) + reuses EM-104 synthetic rows"
CUSTOM_PREFIX = "custom:"
ARCHETYPE = "custom"
DEFAULT_MAX_ITEMS = 50
SEED_MIN = 0
SEED_MAX = 10_000_000
TITLE_MAX = 160

ATTRIBUTION = (
    "Arayüzden yazılmış özel demo senaryoları: EmberMind senaryo düzenleyicisi "
    "(EM-108) — EM-104 üreteci üzerinde doğrulanmış (seed, config); gerçek "
    "gözlem değildir"
)

# A slug key: lowercase alphanumerics + internal hyphens, 3..62 chars, anchored
# at both ends by an alphanumeric so it can never start/end with a hyphen.
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}[a-z0-9]$")


class ScenarioEditorError(SyntheticError):
    """Raised for an invalid authored scenario or an unknown custom key."""


# --------------------------------------------------------------- helpers ---


def _max_items(settings: Any) -> int:
    raw = getattr(settings, "SCENARIO_EDITOR_MAX_ITEMS", DEFAULT_MAX_ITEMS)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioEditorError(
            "SCENARIO_EDITOR_MAX_ITEMS must be an integer"
        ) from exc
    if value < 0:
        raise ScenarioEditorError("SCENARIO_EDITOR_MAX_ITEMS must be >= 0")
    return value


def _normalize_key(key: Any) -> str:
    normalized = str(key).strip().lower()
    if not _KEY_RE.match(normalized):
        raise ScenarioEditorError(
            "scenario key must be 3-62 chars, lowercase letters/digits with "
            "internal hyphens (e.g. 'koyu-ortasu')"
        )
    if normalized in LIBRARY_KEYS:
        raise ScenarioEditorError(
            f"scenario key '{normalized}' clashes with a built-in library key"
        )
    return normalized


def _validate_title(title: Any) -> str:
    cleaned = str(title or "").strip()
    if not cleaned:
        raise ScenarioEditorError("title must not be empty")
    if len(cleaned) > TITLE_MAX:
        raise ScenarioEditorError(f"title must be at most {TITLE_MAX} characters")
    return cleaned


def _validate_seed(seed: Any) -> int:
    try:
        value = int(seed)
    except (TypeError, ValueError) as exc:
        raise ScenarioEditorError("seed must be an integer") from exc
    if not SEED_MIN <= value <= SEED_MAX:
        raise ScenarioEditorError(f"seed must be within [{SEED_MIN}, {SEED_MAX}]")
    return value


def _validated_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize + validate an authored config through the EM-104 engine."""
    if config is not None and not isinstance(config, dict):
        raise ScenarioEditorError("config must be an object")
    # normalize_config deep-copies DEFAULT_CONFIG, merges the authored override
    # and raises SyntheticError on any out-of-range value (bbox, wind hours,
    # outage count/span, resource counts...). We force a scenario_name so every
    # custom definition carries the editor namespace and never aliases a preset.
    merged = dict(config or {})
    merged.setdefault("scenario_name", "custom-scenario")
    # Surface the EM-104 validation failure as an editor error so the route can
    # map every authoring rejection uniformly (same rules, consistent type).
    try:
        return normalize_config(merged)
    except SyntheticError as exc:
        raise ScenarioEditorError(str(exc)) from exc


def _load(session: Session, key: str) -> CustomScenario:
    normalized = str(key).strip().lower()
    row = session.scalar(
        select(CustomScenario).where(CustomScenario.scenario_key == normalized)
    )
    if row is None:
        raise ScenarioEditorError(f"custom scenario '{key}' not found")
    return row


def _summary(row: CustomScenario) -> dict[str, Any]:
    return {**row.as_dict, "preset": f"{CUSTOM_PREFIX}{row.scenario_key}"}


# ------------------------------------------------------------- authoring ---


def create(
    session: Session,
    settings: Any,
    *,
    key: str,
    title: str,
    description: str | None = None,
    seed: int,
    config: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Validate and persist a new authored scenario definition."""
    scenario_key = _normalize_key(key)
    clean_title = _validate_title(title)
    clean_seed = _validate_seed(seed)
    normalized = _validated_config(config)
    cap = _max_items(settings)
    existing = session.scalar(select(func.count()).select_from(CustomScenario))
    if (existing or 0) >= cap:
        raise ScenarioEditorError(
            f"custom scenario limit reached ({cap}); delete one first"
        )
    if session.scalar(
        select(CustomScenario).where(CustomScenario.scenario_key == scenario_key)
    ):
        raise ScenarioEditorError(f"scenario key '{scenario_key}' already exists")
    row = CustomScenario(
        scenario_key=scenario_key,
        title=clean_title,
        description=str(description).strip() if description else None,
        seed=clean_seed,
        config_json=canonical_json(normalized),
        archetype=ARCHETYPE,
        created_by=str(created_by).strip() if created_by else None,
    )
    session.add(row)
    session.flush()
    return _summary(row)


def update(
    session: Session,
    key: str,
    *,
    title: str | None = None,
    description: str | None = None,
    seed: int | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Edit an existing definition in place (only provided fields change)."""
    row = _load(session, key)
    if title is not None:
        row.title = _validate_title(title)  # type: ignore[assignment]
    if description is not None:
        row.description = str(description).strip() or None  # type: ignore[assignment]
    if seed is not None:
        row.seed = _validate_seed(seed)  # type: ignore[assignment]
    if config is not None:
        row.config_json = canonical_json(_validated_config(config))  # type: ignore[assignment]
    session.flush()
    return _summary(row)


def delete(session: Session, key: str) -> dict[str, Any]:
    """Remove one authored scenario definition (operational rows untouched)."""
    row = _load(session, key)
    scenario_key = row.scenario_key
    session.delete(row)
    session.flush()
    return {"status": "deleted", "key": scenario_key}


# ----------------------------------------------------------------- read ---


def list_scenarios(session: Session) -> list[dict[str, Any]]:
    """Authored scenarios, newest first (definition summaries)."""
    rows = session.scalars(
        select(CustomScenario).order_by(CustomScenario.created_at.desc())
    )
    return [_summary(row) for row in rows]


def detail(session: Session, key: str) -> dict[str, Any]:
    """One definition including its parsed (normalized) config."""
    row = _load(session, key)
    payload = _summary(row)
    payload["config"] = json.loads(str(row.config_json))
    return payload


# ------------------------------------------------------ preview/launch ---


def _launch_summary(
    row: CustomScenario, dataset: dict[str, Any], counts: dict[str, int]
) -> dict[str, Any]:
    meta = dataset["meta"]
    return {
        "key": row.scenario_key,
        "title": row.title,
        "archetype": ARCHETYPE,
        "seed": int(row.seed),
        "scenario_tag": str(meta["scenario_tag"]),
        "result_hash": str(meta["result_hash"]),
        "record_count": int(meta["record_count"]),
        "persisted_counts": counts,
        "synthetic_label": SYNTHETIC_LABEL,
    }


def preview(session: Session, key: str) -> dict[str, Any]:
    """Build the authored dataset (no persistence) and return a light summary."""
    row = _load(session, key)
    dataset = build_dataset(int(row.seed), json.loads(str(row.config_json)))
    meta = dataset["meta"]
    return {
        "scenario": _summary(row),
        "scenario_tag": str(meta["scenario_tag"]),
        "result_hash": str(meta["result_hash"]),
        "config_hash": str(meta["config_hash"]),
        "record_count": int(meta["record_count"]),
        "fire": dataset["fire"],
        "outage_zone_count": len(dataset["outage_zones"]),
        "synthetic_label": SYNTHETIC_LABEL,
    }


def activate(session: Session, key: str) -> dict[str, Any]:
    """One-click start an authored scenario: generate + persist + audit run."""
    row = _load(session, key)
    dataset = build_dataset(
        int(row.seed), copy.deepcopy(json.loads(str(row.config_json)))
    )
    counts = persist_dataset(session, dataset)
    run = record_run(
        session, dataset, persisted=True, preset=f"{CUSTOM_PREFIX}{row.scenario_key}"
    )
    summary = _launch_summary(row, dataset, counts)
    summary["run"] = run.as_dict
    return {"status": "activated", "scenario": summary, "attribution": ATTRIBUTION}


# ---------------------------------------------------------------- config ---


def editor_config(settings: Any) -> dict[str, Any]:
    """Read-time descriptor: caps, validation guarantees and library merge."""
    return {
        "version": EDITOR_VERSION,
        "archetype": ARCHETYPE,
        "max_items": _max_items(settings),
        "seed_range": [SEED_MIN, SEED_MAX],
        "title_max_length": TITLE_MAX,
        "key_pattern": _KEY_RE.pattern,
        "reserved_keys": sorted(LIBRARY_KEYS),
        "validation": (
            "config EM-104 normalize_config üzerinden doğrulanır (bbox/rüzgâr "
            "saatleri/kesinti sayısı sınırları)"
        ),
        "determinism": "kayıtlı normalize config + sabit seed → her seferinde aynı hash",
        "launch": "activate = EM-104 build_dataset + persist_dataset + ScenarioRun "
        f"(preset={CUSTOM_PREFIX}<key>)",
        "synthetic_label": SYNTHETIC_LABEL,
        "persistence": EDITOR_PERSISTENCE,
        "attribution": ATTRIBUTION,
    }
