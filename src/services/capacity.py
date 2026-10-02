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
from src.models.capacity_audit import CapacityAssumptionAudit
from src.models.inventory import RESOURCE_TYPES, SuppressionResource
from src.services.inventory import InventoryError, normalize_type
from src.utils.timeutils import utc_now

# The one unit every resource is normalised to, so capacity and risk match.
CAPACITY_UNIT = "ha/saat"

# Fixed attribution for the EM-034 assumption audit view (internal config store).
CAPACITY_AUDIT_ATTRIBUTION = (
    "Kapasite varsayımı denetim kaydı: EmberMind yönetici konfigürasyonu (EM-034)"
)

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
    """Apply admin edits (resource_type -> ha/hour), audit each change.

    EM-034: every value that actually differs from the stored one is recorded
    in the append-only ``capacity_assumption_audit`` table (old -> new, editor,
    timestamp) before the live row is overwritten. Re-saving the same value is
    not a change and is not audited.
    """
    if not values:
        raise CapacityError("no capacity assumptions supplied to update")
    ensure_defaults(session, settings)
    applied = 0
    for resource_type, raw in values.items():
        canonical, ha_per_hour = _validate_value(resource_type, raw)
        row = _get_row(session, canonical)
        if row is None:  # ensure_defaults covers known types; defensive anyway
            row = CapacityAssumption(resource_type=canonical, ha_per_hour=ha_per_hour)
            session.add(row)
        old_value = float(row.ha_per_hour)
        if old_value != ha_per_hour:
            session.add(
                CapacityAssumptionAudit(
                    resource_type=canonical,
                    old_value=old_value,
                    new_value=ha_per_hour,
                    updated_by=updated_by,
                )
            )
            applied += 1
        row.ha_per_hour = ha_per_hour  # type: ignore[assignment]
        row.updated_by = updated_by  # type: ignore[assignment]
    session.flush()
    return {**list_assumptions(session, settings), "applied_count": applied}


def list_audit(
    session: Session,
    settings: Any,
    *,
    resource_type: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Read the append-only capacity-assumption audit history (EM-034).

    Newest first, optionally scoped to one resource type and clamped to a page
    size. The audit table is never seeded, so reading it does not write any
    change rows; only a real value edit adds one.
    """
    max_limit = int(getattr(settings, "CAPACITY_AUDIT_MAX_LIMIT", 200))
    default_limit = int(getattr(settings, "CAPACITY_AUDIT_DEFAULT_LIMIT", 50))
    page_limit = default_limit if limit is None else max(1, min(int(limit), max_limit))
    stmt = select(CapacityAssumptionAudit).order_by(CapacityAssumptionAudit.id.desc())
    count_stmt = select(func.count()).select_from(CapacityAssumptionAudit)
    if resource_type:
        stmt = stmt.where(CapacityAssumptionAudit.resource_type == resource_type)
        count_stmt = count_stmt.where(
            CapacityAssumptionAudit.resource_type == resource_type
        )
    total = int(session.scalar(count_stmt) or 0)
    rows = session.scalars(stmt.limit(page_limit)).all()
    return {
        "unit": CAPACITY_UNIT,
        "resource_type": resource_type,
        "limit": page_limit,
        "total_matching": total,
        "entries": [row.as_dict for row in rows],
        "attribution": CAPACITY_AUDIT_ATTRIBUTION,
    }


def available_counts_by_type(session: Session) -> dict[str, int]:
    """Count of currently-available resources per type from the inventory."""
    rows = session.execute(
        select(SuppressionResource.resource_type, func.count())
        .where(SuppressionResource.status == "available")
        .group_by(SuppressionResource.resource_type)
    ).all()
    return {str(rtype): int(count) for rtype, count in rows}


def enroute_arrival_minutes(session: Session) -> list[tuple[str, int]]:
    """``(resource_type, minutes_until_arrival)`` for ETA-committed en-route units.

    EM-033 makes capacity time-dependent: an ``en_route`` asset that has a
    committed ``arrival_eta`` is scheduled to come online that many minutes from
    now. The value is clamped to ``>= 0`` so an already-passed ETA is treated as
    on station now. En-route assets **without** an ETA are deliberately left out
    -- they keep the EM-031 behaviour of contributing nothing until they flip to
    ``available`` -- so the current effective capacity is never inflated.
    """
    now = utc_now()
    rows = session.execute(
        select(
            SuppressionResource.resource_type,
            SuppressionResource.arrival_eta,
            func.count(),
        )
        .where(SuppressionResource.status == "en_route")
        .where(SuppressionResource.arrival_eta.is_not(None))
        .group_by(
            SuppressionResource.resource_type,
            SuppressionResource.arrival_eta,
        )
    ).all()
    out: list[tuple[str, int]] = []
    for rtype, eta, count in rows:
        if eta is None:
            continue
        minute = max(0, int(round((eta - now).total_seconds() / 60.0)))
        for _ in range(int(count)):
            out.append((str(rtype), minute))
    return out


def capacity_at_minute(
    base_total: float,
    assumptions: dict[str, float],
    arrivals: list[tuple[str, int]],
    minute: int,
) -> float:
    """Effective capacity (ha/hour) at ``minute``: now-capacity + units arrived.

    ``base_total`` is the current :func:`effective_capacity` total (available
    only, EM-028); every en-route arrival whose ETA is at or before ``minute``
    adds its type's per-unit assumption. Pure arithmetic so callers can read the
    DB once and evaluate the whole horizon schedule.
    """
    extra = 0.0
    for rtype, eta_minute in arrivals:
        if eta_minute <= minute:
            extra += float(assumptions.get(rtype, 0.0))
    return round(float(base_total) + extra, 3)


def capacity_schedule(
    session: Session,
    settings: Any,
    minutes: list[int],
) -> dict[str, Any]:
    """Capacity (ha/hour) evaluated at each of ``minutes`` (EM-033).

    Returns the ``base_ha_h`` (available-only now capacity), the per-minute
    ``schedule`` and the discrete ``arrivals`` (minute + per-unit ha/hour) that
    step it up, so the timeline and the risk bands can be re-priced against the
    capacity that will actually be on station at each horizon.
    """
    assumptions = assumption_map(session, settings)
    base_total = float(
        effective_capacity(session, settings)["total_effective_ha_per_hour"]
    )
    arrivals = enroute_arrival_minutes(session)
    schedule = {
        int(minute): capacity_at_minute(base_total, assumptions, arrivals, int(minute))
        for minute in minutes
    }
    arrival_rows = sorted(
        (
            minute,
            rtype,
            float(assumptions.get(rtype, 0.0)),
        )
        for rtype, minute in arrivals
    )
    return {
        "unit": CAPACITY_UNIT,
        "base_ha_h": round(base_total, 3),
        "time_dependent": bool(arrivals),
        "arrivals": [
            {"minute": minute, "resource_type": rtype, "ha_per_hour": ha}
            for minute, rtype, ha in arrival_rows
        ],
        "schedule": schedule,
    }


# Country bucket for resources that never declared one, so a per-country view
# surfaces them explicitly instead of silently folding them into another
# country's total (EM-064 "no screen merges two countries quietly").
UNASSIGNED_COUNTRY = "atanmamış"


def _counts_by_country_type(session: Session) -> dict[tuple[str, str], int]:
    """``{(country, resource_type): count}`` for currently-available resources."""
    rows = session.execute(
        select(
            SuppressionResource.country,
            SuppressionResource.resource_type,
            func.count(),
        )
        .where(SuppressionResource.status == "available")
        .group_by(SuppressionResource.country, SuppressionResource.resource_type)
    ).all()
    return {
        (str(country) if country else UNASSIGNED_COUNTRY, str(rtype)): int(count)
        for country, rtype, count in rows
    }


def capacity_by_country(session: Session, settings: Any) -> dict[str, Any]:
    """Per-country capacity account (EM-064): two nations never merge silently.

    Mirrors :func:`effective_capacity` but buckets the available inventory by
    each resource's declared ``country`` first. Resources with no country are
    isolated in an explicit :data:`UNASSIGNED_COUNTRY` bucket rather than being
    folded into any country, and ``merged_by_default`` is always ``False`` so a
    caller cannot treat this as one pooled figure. Summing every country's total
    equals the global :func:`effective_capacity` total.
    """
    assumptions = assumption_map(session, settings)
    counts = _counts_by_country_type(session)
    by_country: dict[str, dict[str, Any]] = {}
    grand_total = 0.0
    for (country, rtype), available in counts.items():
        if rtype not in assumptions:  # only known, normalisable types count
            continue
        ha_per_hour = float(assumptions[rtype])
        effective = round(available * ha_per_hour, 3)
        bucket = by_country.setdefault(
            country,
            {
                "country": country,
                "by_type": {},
                "total_effective_ha_per_hour": 0.0,
            },
        )
        bucket["by_type"][rtype] = {
            "available": available,
            "ha_per_hour": ha_per_hour,
            "effective_ha_per_hour": effective,
        }
        bucket["total_effective_ha_per_hour"] = round(
            bucket["total_effective_ha_per_hour"] + effective, 3
        )
        grand_total += effective
    for bucket in by_country.values():
        bucket["by_type"] = {
            rtype: bucket["by_type"][rtype] for rtype in sorted(bucket["by_type"])
        }
    return {
        "unit": CAPACITY_UNIT,
        "merged_by_default": False,
        "countries": sorted(by_country.values(), key=lambda row: row["country"]),
        "grand_total_effective_ha_per_hour": round(grand_total, 3),
    }


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
