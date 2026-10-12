"""Per-region silent-zone sensitivity and threshold tuning (EM-044, Epic E4).

EM-035 learns one *global* silence z-score and EM-040 alerts on one *global*
minimum. But the right "how quiet counts as silent" and "how long before we ping
the operator" differ region to region - raising the z-score catches faint
blackouts at the cost of more false alarms, lengthening the minimum silence buys
confidence at the cost of later alerts. That trade-off belongs to the operator
(EM-044 acceptance: "eşik ve minimum sessizlik süresi arayüzden ayarlanır;
değişiklik denetim kaydına yazılır; varsayılana dönme seçeneği vardır").

This service owns that tuning. It composes an **effective** value per region
(global default overlaid by a persisted per-region override), lets the operator
**set** one or both knobs and **reset** a region back to the default. Every
change is written to the unified ``audit_trail`` ledger under the ``threshold``
domain (reusing EM-096's append-only record, so no second audit table) with the
who / when / old -> new. The override table itself only stores the knobs the
operator actually moved - a ``NULL`` column inherits the default, and a reset
drops the row entirely.
"""
from __future__ import annotations

import secrets
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.silent_zone_tuning import SilentZoneTuning
from src.models.spatial import SilentRegion
from src.services.audit_trail import record_audit

# Global defaults the operator's overrides are layered on top of. These mirror
# the EM-035 sensitivity (z-score below which a cell is "silent") and a sensible
# 6-hour floor before EM-040 pings; both are re-read from settings so the values
# here are only the fallback when a key is absent (a bare object() in tests).
DEFAULT_SENSITIVITY_Z = 1.5
DEFAULT_MIN_SILENCE_HOURS = 6.0

# Bound the knobs so a typo cannot disable detection or spam alerts every hour.
DEFAULT_MIN_SENSITIVITY_Z = 0.5
DEFAULT_MAX_SENSITIVITY_Z = 5.0
DEFAULT_MIN_SILENCE_HOURS_FLOOR = 0.0
DEFAULT_MAX_SILENCE_HOURS_CEIL = 168.0

DEFAULT_MAX_LIMIT = 200

SILENT_ZONE_TUNING_ATTRIBUTION = (
    "EM-044: sessiz bölge eşik (hassasiyet z-skoru) ve minimum sessizlik süresi "
    "bölge bazında arayüzden ayarlanır; ayarlanmamış bölge varsayılanı devralır; "
    "her değişiklik tekilleştirilmiş denetim defterine (threshold alanı) yazılır "
    "ve bölge varsayılana döndürülebilir"
)
SILENT_ZONE_TUNING_PERSISTENCE = "silent_zone_tuning"
AUDIT_DOMAIN = "threshold"


class SilentZoneTuningError(ValueError):
    """Raised for an invalid tuning request (bad value, missing region)."""


def _default_sensitivity(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_TUNING_DEFAULT_SENSITIVITY_Z", DEFAULT_SENSITIVITY_Z)
    )


def _default_min_silence(settings: Any) -> float:
    return float(
        getattr(
            settings,
            "SILENT_TUNING_DEFAULT_MIN_SILENCE_HOURS",
            DEFAULT_MIN_SILENCE_HOURS,
        )
    )


def _sensitivity_bounds(settings: Any) -> tuple[float, float]:
    low = float(
        getattr(settings, "SILENT_TUNING_MIN_SENSITIVITY_Z", DEFAULT_MIN_SENSITIVITY_Z)
    )
    high = float(
        getattr(settings, "SILENT_TUNING_MAX_SENSITIVITY_Z", DEFAULT_MAX_SENSITIVITY_Z)
    )
    return low, high


def _min_silence_bounds(settings: Any) -> tuple[float, float]:
    low = float(
        getattr(
            settings, "SILENT_TUNING_MIN_SILENCE_HOURS", DEFAULT_MIN_SILENCE_HOURS_FLOOR
        )
    )
    high = float(
        getattr(
            settings, "SILENT_TUNING_MAX_SILENCE_HOURS", DEFAULT_MAX_SILENCE_HOURS_CEIL
        )
    )
    return low, high


def _max_limit(settings: Any) -> int:
    return int(getattr(settings, "SILENT_TUNING_MAX_LIMIT", DEFAULT_MAX_LIMIT))


def _new_key() -> str:
    """A short, URL-safe unique tuning key (collision negligible)."""
    return f"szu-{secrets.token_hex(6)}"


def _clean_actor(value: Optional[str]) -> str:
    text = str(value).strip() if value is not None else ""
    return (text or "operator")[:64]


def _validate_sensitivity(value: float, settings: Any) -> float:
    low, high = _sensitivity_bounds(settings)
    number = float(value)
    if not low <= number <= high:
        raise SilentZoneTuningError(
            f"sensitivity_z {value!r} {low}..{high} aralığında olmalı"
        )
    return round(number, 4)


def _validate_min_silence(value: float, settings: Any) -> float:
    low, high = _min_silence_bounds(settings)
    number = float(value)
    if not low <= number <= high:
        raise SilentZoneTuningError(
            f"min_silence_hours {value!r} {low}..{high} aralığında olmalı"
        )
    return round(number, 2)


def _resolve_region(session: Session, region_id: int) -> SilentRegion:
    """Fetch the silent region a tuning targets or raise a not-found error."""
    region = session.scalar(
        select(SilentRegion).where(SilentRegion.id == int(region_id))
    )
    if region is None:
        raise SilentZoneTuningError(f"silent region '{region_id}' not found")
    return region


def get_override(session: Session, region_id: int) -> Optional[dict[str, Any]]:
    """The raw persisted override for a region, or ``None`` when untuned."""
    row = session.scalar(
        select(SilentZoneTuning).where(SilentZoneTuning.region_id == int(region_id))
    )
    return row.as_dict if row is not None else None


def _effective_pair(
    override: Optional[dict[str, Any]], settings: Any
) -> dict[str, Any]:
    """Merge one override snapshot with the defaults into effective values."""
    stored = override or {}
    default_z = round(_default_sensitivity(settings), 4)
    default_hours = round(_default_min_silence(settings), 2)
    override_z = stored.get("sensitivity_z")
    override_hours = stored.get("min_silence_hours")
    sensitivity_z = default_z if override_z is None else round(float(override_z), 4)
    min_silence = (
        default_hours if override_hours is None else round(float(override_hours), 2)
    )
    return {
        "sensitivity_z": sensitivity_z,
        "min_silence_hours": min_silence,
        "sensitivity_source": "override" if override_z is not None else "default",
        "min_silence_source": "override" if override_hours is not None else "default",
        "override": stored or None,
    }


def effective_for_region(
    session: Session, settings: Any, region_id: int
) -> dict[str, Any]:
    """Effective tuning for one region, validated against an existing region."""
    region = _resolve_region(session, region_id)
    override = get_override(session, region_id)
    payload = _effective_pair(override, settings)
    return {
        "region_id": int(region.id),
        "region_name": region.region_name,
        "is_overridden": override is not None,
        **payload,
    }


def list_effective(session: Session, settings: Any) -> list[dict[str, Any]]:
    """Every active silent region with its effective tuning, tuned first.

    A single pass loads the override rows keyed by region so the read stays one
    query per table rather than a query per region.
    """
    overrides: dict[int, dict[str, Any]] = {}
    for row in session.scalars(select(SilentZoneTuning)).all():
        overrides[int(row.region_id)] = row.as_dict

    bounded = _max_limit(settings)
    regions = session.scalars(
        select(SilentRegion)
        .where(SilentRegion.is_active.is_(True))
        .order_by(SilentRegion.id)
        .limit(bounded)
    ).all()
    rows: list[dict[str, Any]] = []
    for region in regions:
        override = overrides.get(int(region.id))
        payload = _effective_pair(override, settings)
        rows.append(
            {
                "region_id": int(region.id),
                "region_name": region.region_name,
                "is_overridden": override is not None,
                "updated_by": (override or {}).get("updated_by"),
                **payload,
            }
        )
    rows.sort(key=lambda item: (not item["is_overridden"], str(item["region_name"])))
    return rows


# pylint: disable-next=too-many-arguments  # explicit knobs beat a magic dict here
def set_tuning(
    session: Session,
    settings: Any,
    region_id: int,
    *,
    sensitivity_z: Optional[float] = None,
    min_silence_hours: Optional[float] = None,
    actor: Optional[str] = None,
) -> dict[str, Any]:
    """Persist (upsert) one region's override knobs and audit the change.

    At least one knob must be supplied; a ``None`` knob leaves the existing
    override for that knob untouched (use :func:`reset_tuning` to fall back to
    the default). The old -> new override snapshot is written to the unified
    ledger under the ``threshold`` domain.
    """
    if sensitivity_z is None and min_silence_hours is None:
        raise SilentZoneTuningError(
            "en az bir ayar (sensitivity_z veya min_silence_hours) verilmeli"
        )

    region = _resolve_region(session, region_id)
    row = session.scalar(
        select(SilentZoneTuning).where(SilentZoneTuning.region_id == int(region_id))
    )

    old_snapshot = row.as_dict if row is not None else None
    created = row is None
    if row is None:
        row = SilentZoneTuning(tuning_key=_new_key(), region_id=int(region_id))
        session.add(row)

    # Legacy ``Column(...)`` mutation is done through ``setattr`` so mypy (which
    # runs without the SQLAlchemy plugin here) sees an ``Any`` value rather than
    # a ``Column[float]`` vs ``float`` mismatch - same idiom as inventory.py.
    if sensitivity_z is not None:
        setattr(row, "sensitivity_z", _validate_sensitivity(sensitivity_z, settings))
    if min_silence_hours is not None:
        setattr(
            row, "min_silence_hours", _validate_min_silence(min_silence_hours, settings)
        )

    clean_actor = _clean_actor(actor)
    setattr(row, "updated_by", clean_actor)
    session.flush()

    audit = record_audit(
        session,
        settings,
        AUDIT_DOMAIN,
        "create" if created else "update",
        clean_actor,
        detail={
            "subject_key": f"silent-region:{int(region.id)}",
            "summary": (
                f"EM-044 {region.region_name}: eşik/min-sessizlik "
                f"{'oluşturuldu' if created else 'güncellendi'}"
            ),
            "old_value": _override_snapshot(old_snapshot),
            "new_value": _override_snapshot(row.as_dict),
        },
    )
    return {
        "tuning": row.as_dict,
        "effective": effective_for_region(session, settings, int(region_id)),
        "created": created,
        "audit": audit,
    }


def reset_tuning(
    session: Session,
    settings: Any,
    region_id: int,
    *,
    actor: Optional[str] = None,
) -> dict[str, Any]:
    """Drop a region's override so it inherits the global default again.

    Idempotent: resetting an already-default region is a no-op (no audit row).
    A real reset writes a ``delete`` entry to the unified ledger.
    """
    region = _resolve_region(session, region_id)
    row = session.scalar(
        select(SilentZoneTuning).where(SilentZoneTuning.region_id == int(region_id))
    )
    if row is None:
        return {
            "reset": False,
            "already_default": True,
            "effective": effective_for_region(session, settings, int(region_id)),
            "audit": None,
        }

    old_snapshot = _override_snapshot(row.as_dict)
    clean_actor = _clean_actor(actor)
    session.delete(row)
    session.flush()

    audit = record_audit(
        session,
        settings,
        AUDIT_DOMAIN,
        "delete",
        clean_actor,
        detail={
            "subject_key": f"silent-region:{int(region_id)}",
            "summary": f"EM-044 {region.region_name}: varsayılana döndürüldü",
            "old_value": old_snapshot,
            "new_value": None,
        },
    )
    return {
        "reset": True,
        "already_default": False,
        "effective": effective_for_region(session, settings, int(region_id)),
        "audit": audit,
    }


def _override_snapshot(override: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Project just the two tunable knobs (+ actor) into the audit snapshot."""
    if not override:
        return None
    return {
        "sensitivity_z": override.get("sensitivity_z"),
        "min_silence_hours": override.get("min_silence_hours"),
        "updated_by": override.get("updated_by"),
    }


def tuning_config(settings: Any = None) -> dict[str, Any]:
    """Descriptor: defaults, bounds and the audit/persistence policy."""
    sens_low, sens_high = _sensitivity_bounds(settings)
    hour_low, hour_high = _min_silence_bounds(settings)
    return {
        "knobs": ["sensitivity_z", "min_silence_hours"],
        "defaults": {
            "sensitivity_z": round(_default_sensitivity(settings), 4),
            "min_silence_hours": round(_default_min_silence(settings), 2),
        },
        "bounds": {
            "sensitivity_z": {"min": sens_low, "max": sens_high},
            "min_silence_hours": {"min": hour_low, "max": hour_high},
        },
        "inheritance_rule": "ayarlanmamış (NULL) knob global varsayılanı devralır",
        "reset_semantics": "bölge satırı silinir, varsayılana döner",
        "audit_domain": AUDIT_DOMAIN,
        "max_limit": _max_limit(settings),
        "attribution": SILENT_ZONE_TUNING_ATTRIBUTION,
        "persistence": SILENT_ZONE_TUNING_PERSISTENCE,
    }


__all__ = [
    "AUDIT_DOMAIN",
    "SILENT_ZONE_TUNING_ATTRIBUTION",
    "SILENT_ZONE_TUNING_PERSISTENCE",
    "SilentZoneTuningError",
    "effective_for_region",
    "get_override",
    "list_effective",
    "reset_tuning",
    "set_tuning",
    "tuning_config",
]
