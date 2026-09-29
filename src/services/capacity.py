"""Capacity unit definition and normalisation (EM-028, Epic E3).

Capacity and risk can only be compared through one index when both are
expressed in the same unit. This service owns the admin-editable per-resource
type "effective suppression capacity" assumption (hectare/hour), seeds it from
config defaults and normalises the live inventory into a single ha/hour figure
so the command panel can show a meaningful capacity account next to risk.
"""
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.capacity import CapacityAssumption
from src.models.inventory import RESOURCE_TYPES, SuppressionResource
from src.services.inventory import InventoryError, normalize_type

# The one unit every resource is normalised to, so capacity and risk match.
CAPACITY_UNIT = "ha/saat"

# Fallbacks used only when a settings object omits the keys entirely (tests may
# pass a lightweight namespace). Real config always provides these values.
_DEFAULT_HA_PER_HOUR = {"crew": 2.0, "helicopter": 12.0, "uav": 4.0}
_DEFAULT_ATTR = {
    "crew": "CAPACITY_HA_PER_HOUR_CREW",
    "helicopter": "CAPACITY_HA_PER_HOUR_HELICOPTER",
    "uav": "CAPACITY_HA_PER_HOUR_UAV",
}


class CapacityError(RuntimeError):
    """Raised for invalid capacity-assumption operations (bad type, negative)."""


def default_ha_per_hour(settings: Any) -> dict[str, float]:
    """Per-resource-type default effective capacity (ha/hour) read from config."""
    return {
        rtype: float(
            getattr(settings, _DEFAULT_ATTR[rtype], _DEFAULT_HA_PER_HOUR[rtype])
        )
        for rtype in RESOURCE_TYPES
    }


def _get_row(session: Session, resource_type: str) -> CapacityAssumption | None:
    return session.scalar(
        select(CapacityAssumption).where(
            CapacityAssumption.resource_type == resource_type
        )
    )


def ensure_defaults(session: Session, settings: Any) -> None:
    """Insert a seeded row for any resource type that has no assumption yet."""
    defaults = default_ha_per_hour(settings)
    for rtype in RESOURCE_TYPES:
        if _get_row(session, rtype) is None:
            session.add(
                CapacityAssumption(
                    resource_type=rtype, ha_per_hour=defaults[rtype], updated_by=None
                )
            )
    session.flush()


def assumption_map(session: Session, settings: Any) -> dict[str, float]:
    """Current resource_type -> ha/hour assumptions, seeded from defaults."""
    ensure_defaults(session, settings)
    rows = session.scalars(
        select(CapacityAssumption).order_by(CapacityAssumption.resource_type)
    ).all()
    return {str(row.resource_type): float(row.ha_per_hour) for row in rows}


def list_assumptions(session: Session, settings: Any) -> dict[str, Any]:
    """Admin-facing view of every capacity unit assumption."""
    values = assumption_map(session, settings)
    return {
        "unit": CAPACITY_UNIT,
        "defaults": default_ha_per_hour(settings),
        "assumptions": [
            {"resource_type": rtype, "ha_per_hour": values[rtype]}
            for rtype in sorted(values)
        ],
    }


def _validate_value(resource_type: str, value: Any) -> tuple[str, float]:
    try:
        canonical = normalize_type(resource_type)
    except InventoryError as exc:  # reuse the inventory type vocabulary
        raise CapacityError(str(exc)) from exc
    try:
        ha_per_hour = float(value)
    except (TypeError, ValueError) as exc:
        raise CapacityError(f"ha_per_hour for '{canonical}' must be numeric") from exc
    if ha_per_hour < 0:
        raise CapacityError(f"ha_per_hour for '{canonical}' must be >= 0")
    return canonical, ha_per_hour


def update_assumptions(
    session: Session,
    settings: Any,
    values: dict[str, Any],
    updated_by: str | None = None,
) -> dict[str, Any]:
    """Apply admin edits (resource_type -> ha/hour) and return the new view."""
    if not values:
        raise CapacityError("no capacity assumptions supplied to update")
    ensure_defaults(session, settings)
    for resource_type, raw in values.items():
        canonical, ha_per_hour = _validate_value(resource_type, raw)
        row = _get_row(session, canonical)
        if row is None:  # ensure_defaults covers known types; defensive anyway
            row = CapacityAssumption(resource_type=canonical, ha_per_hour=ha_per_hour)
            session.add(row)
        row.ha_per_hour = ha_per_hour  # type: ignore[assignment]
        row.updated_by = updated_by  # type: ignore[assignment]
    session.flush()
    return list_assumptions(session, settings)


def available_counts_by_type(session: Session) -> dict[str, int]:
    """Count of currently-available resources per type from the inventory."""
    rows = session.execute(
        select(SuppressionResource.resource_type, func.count())
        .where(SuppressionResource.status == "available")
        .group_by(SuppressionResource.resource_type)
    ).all()
    return {str(rtype): int(count) for rtype, count in rows}


def effective_capacity(session: Session, settings: Any) -> dict[str, Any]:
    """Normalise the available inventory into one ha/hour capacity account."""
    assumptions = assumption_map(session, settings)
    counts = available_counts_by_type(session)
    by_type: dict[str, dict[str, Any]] = {}
    total = 0.0
    for rtype in RESOURCE_TYPES:
        available = int(counts.get(rtype, 0))
        ha_per_hour = float(assumptions.get(rtype, 0.0))
        effective = round(available * ha_per_hour, 3)
        total += effective
        by_type[rtype] = {
            "available": available,
            "ha_per_hour": ha_per_hour,
            "effective_ha_per_hour": effective,
        }
    return {
        "unit": CAPACITY_UNIT,
        "by_type": by_type,
        "total_effective_ha_per_hour": round(total, 3),
    }
