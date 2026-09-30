"""Suppression resource inventory CRUD and CSV bulk import (EM-103).

The coordinator manages deployable assets (crew / helicopter / uav) so the
capacity picture stays current. This service owns validation, the CRUD
operations, a deterministic capacity summary and a tolerant CSV importer that
upserts by ``resource_key``.
"""
import csv
import io
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.inventory import (
    RESOURCE_STATUSES,
    RESOURCE_TYPES,
    SuppressionResource,
)
from src.utils.timeutils import utc_now

# Turkish / abbreviation aliases accepted in API payloads and CSV files.
TYPE_ALIASES = {
    "crew": "crew",
    "ekip": "crew",
    "arazoz": "crew",
    "ground": "crew",
    "helicopter": "helicopter",
    "helikopter": "helicopter",
    "helik": "helicopter",
    "air": "helicopter",
    "uav": "uav",
    "iha": "uav",
    "drone": "uav",
}
STATUS_ALIASES = {
    "available": "available",
    "müsait": "available",
    "musait": "available",
    "aktif": "available",
    "deployed": "deployed",
    "görevde": "deployed",
    "gorevde": "deployed",
    "en_route": "en_route",
    "en-route": "en_route",
    "enroute": "en_route",
    "yolda": "en_route",
    "maintenance": "maintenance",
    "bakim": "maintenance",
    "bakım": "maintenance",
    "out_of_service": "out_of_service",
    "arıza": "out_of_service",
    "ariza": "out_of_service",
    "unavailable": "out_of_service",
}

# CSV header aliases -> canonical field names.
CSV_HEADER_ALIASES = {
    "resource_key": "resource_key",
    "key": "resource_key",
    "id": "resource_key",
    "name": "name",
    "ad": "name",
    "resource_type": "resource_type",
    "type": "resource_type",
    "tur": "resource_type",
    "latitude": "latitude",
    "lat": "latitude",
    "enlem": "latitude",
    "longitude": "longitude",
    "lon": "longitude",
    "lng": "longitude",
    "boylam": "longitude",
    "base_key": "base_key",
    "base": "base_key",
    "us": "base_key",
    "country": "country",
    "ulke": "country",
    "status": "status",
    "durum": "status",
    "capacity": "capacity",
    "kapasite": "capacity",
    "capacity_unit": "capacity_unit",
    "unit": "capacity_unit",
    "arrival_minutes": "arrival_minutes",
    "eta_minutes": "arrival_minutes",
    "varis": "arrival_minutes",
    "vars_zaman": "arrival_minutes",
}

CSV_REQUIRED_COLUMNS = ("resource_key", "resource_type", "latitude", "longitude")

# Hard cap for one bulk import: unbounded CSV bodies would otherwise let a
# single request balloon transactions, error lists and memory in the worker.
MAX_CSV_ROWS = 5000

# Turkish letters that break a plain ``str.lower()`` match: the dotted capital
# "İ" decomposes to "i" + combining dot, and dotless "ı"/accented vowels must
# fold to the ASCII keys used throughout the alias tables below.
_TR_FOLD = str.maketrans(
    "İIıÜüÖöŞşÇçĞğ",
    "iiiuuoossccgg",
)


def _fold(value: Any) -> str:
    """Casefold a token to the ASCII keys used in the alias tables."""
    return str(value or "").strip().translate(_TR_FOLD).lower()


class InventoryError(RuntimeError):
    """Raised for invalid inventory operations (unknown key, bad vocabulary)."""


def normalize_type(value: Any) -> str:
    """Map a resource type token (any case/alias) to the canonical vocabulary."""
    text = _fold(value)
    canonical = TYPE_ALIASES.get(text)
    if canonical is None:
        raise InventoryError(
            f"invalid resource_type '{value}'; expected one of {list(RESOURCE_TYPES)}"
        )
    return canonical


def normalize_status(value: Any) -> str:
    """Map a status token (any case/alias) to the canonical vocabulary."""
    text = _fold(value)
    canonical = STATUS_ALIASES.get(text)
    if canonical is None:
        raise InventoryError(
            f"invalid status '{value}'; expected one of {list(RESOURCE_STATUSES)}"
        )
    return canonical


def _validate_coords(latitude: Any, longitude: Any) -> tuple[float, float]:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise InventoryError("latitude/longitude must be numeric") from exc
    if not -90.0 <= lat <= 90.0:
        raise InventoryError(f"latitude {lat} out of range [-90, 90]")
    if not -180.0 <= lon <= 180.0:
        raise InventoryError(f"longitude {lon} out of range [-180, 180]")
    return round(lat, 6), round(lon, 6)


def _validate_capacity(capacity: Any) -> float:
    try:
        value = float(capacity)
    except (TypeError, ValueError) as exc:
        raise InventoryError("capacity must be numeric") from exc
    if value < 0:
        raise InventoryError("capacity must be >= 0")
    return value


def _parse_arrival(value: Any) -> Any:
    """Normalise an EM-033 arrival input to a naive-UTC datetime or None.

    Accepts ``None`` (no committed arrival), an ISO-8601 string (a trailing
    ``Z`` is dropped so it parses to naive UTC) or a non-negative number of
    minutes from now (``arrival_minutes``/``eta_minutes``), matching how the
    operator map already reasons about "T+dk". A negative or unparseable value
    is rejected so capacity is never scheduled from a bad ETA.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minutes = float(value)
        if minutes < 0:
            raise InventoryError("arrival_minutes must be >= 0")
        return utc_now() + timedelta(minutes=minutes)
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 2 and text[-1] in ("Z", "z"):
        text = text[:-1]
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise InventoryError(f"invalid arrival_eta '{value}'") from exc


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def get_resource(session: Session, resource_key: str) -> SuppressionResource | None:
    """Fetch one inventory record by its unique key."""
    return session.scalar(
        select(SuppressionResource).where(
            SuppressionResource.resource_key == resource_key
        )
    )


def list_resources(
    session: Session,
    resource_type: str | None = None,
    status: str | None = None,
    base_key: str | None = None,
    country: str | None = None,
    limit: int = 500,
) -> list[SuppressionResource]:
    """Filterable inventory listing ordered by key."""
    query = select(SuppressionResource).order_by(SuppressionResource.resource_key)
    if resource_type:
        query = query.where(
            SuppressionResource.resource_type == normalize_type(resource_type)
        )
    if status:
        query = query.where(SuppressionResource.status == normalize_status(status))
    if base_key:
        query = query.where(SuppressionResource.base_key == base_key)
    if country:
        query = query.where(SuppressionResource.country == country)
    return list(session.scalars(query.limit(int(limit))))


def _parse_limit(value: Any, field: str) -> float | None:
    """EM-050 optional positive limit; ``None`` stays unconstrained."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InventoryError(f"invalid {field} '{value}'") from exc
    if number <= 0:
        raise InventoryError(f"{field} must be positive")
    return number


def _parse_bool_limit(value: Any) -> bool | None:
    """EM-050 tri-state flag: None = unknown, else True/False."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise InventoryError(f"invalid boolean '{value}'")


def create_resource(session: Session, data: dict[str, Any]) -> SuppressionResource:
    """Validate and insert a new inventory record (unique resource_key)."""
    resource_key = _clean_str(data.get("resource_key"))
    if not resource_key:
        raise InventoryError("resource_key is required")
    if get_resource(session, resource_key):
        raise InventoryError(f"resource '{resource_key}' already exists")
    lat, lon = _validate_coords(data.get("latitude"), data.get("longitude"))
    resource = SuppressionResource(
        resource_key=resource_key,
        name=_clean_str(data.get("name")) or resource_key,
        resource_type=normalize_type(data.get("resource_type")),
        latitude=lat,
        longitude=lon,
        base_key=_clean_str(data.get("base_key")),
        country=_clean_str(data.get("country")),
        status=normalize_status(data.get("status") or "available"),
        capacity=_validate_capacity(data.get("capacity", 0.0)),
        capacity_unit=_clean_str(data.get("capacity_unit")),
        range_km=_parse_limit(data.get("range_km"), "range_km"),
        shift_minutes=_parse_limit(data.get("shift_minutes"), "shift_minutes"),
        night_capable=_parse_bool_limit(data.get("night_capable")),
        arrival_eta=_parse_arrival(
            data.get(
                "arrival_minutes", data.get("eta_minutes", data.get("arrival_eta"))
            )
        ),
    )
    session.add(resource)
    session.flush()
    return resource


def update_resource(
    session: Session, resource_key: str, changes: dict[str, Any]
) -> SuppressionResource:
    """Apply a partial update to an existing record; unknown fields rejected."""
    resource = get_resource(session, resource_key)
    if resource is None:
        raise InventoryError(f"resource '{resource_key}' not found")
    editable = {
        "name",
        "resource_type",
        "latitude",
        "longitude",
        "base_key",
        "country",
        "status",
        "capacity",
        "capacity_unit",
        "arrival_minutes",
        "eta_minutes",
        "arrival_eta",
        "range_km",
        "shift_minutes",
        "night_capable",
    }
    unknown = set(changes) - editable
    if unknown:
        raise InventoryError(f"unknown fields: {sorted(unknown)}")
    if "resource_type" in changes and changes["resource_type"] is not None:
        resource.resource_type = normalize_type(changes["resource_type"])  # type: ignore[assignment]
    if "status" in changes and changes["status"] is not None:
        resource.status = normalize_status(changes["status"])  # type: ignore[assignment]
    if "latitude" in changes or "longitude" in changes:
        lat, lon = _validate_coords(
            changes.get("latitude", resource.latitude),
            changes.get("longitude", resource.longitude),
        )
        resource.latitude = lat  # type: ignore[assignment]
        resource.longitude = lon  # type: ignore[assignment]
    if "capacity" in changes and changes["capacity"] is not None:
        resource.capacity = _validate_capacity(changes["capacity"])  # type: ignore[assignment]
    if (
        "arrival_minutes" in changes
        or "eta_minutes" in changes
        or "arrival_eta" in changes
    ):
        raw = changes.get(
            "arrival_minutes",
            changes.get("eta_minutes", changes.get("arrival_eta")),
        )
        resource.arrival_eta = _parse_arrival(raw)  # type: ignore[assignment]
    for field in ("name", "base_key", "country", "capacity_unit"):
        if field in changes:
            setattr(resource, field, _clean_str(changes[field]))
    # EM-050 optional deployability limits (None clears back to unconstrained).
    for field in ("range_km", "shift_minutes"):
        if field in changes:
            setattr(resource, field, _parse_limit(changes[field], field))
    if "night_capable" in changes:
        resource.night_capable = _parse_bool_limit(changes["night_capable"])  # type: ignore[assignment]
    session.flush()
    return resource


def delete_resource(session: Session, resource_key: str) -> bool:
    """Remove a record; returns False when the key is unknown."""
    resource = get_resource(session, resource_key)
    if resource is None:
        return False
    session.delete(resource)
    session.flush()
    return True


def capacity_summary(session: Session) -> dict[str, Any]:
    """Deterministic capacity rollup per resource type for the coordinator."""
    by_type: dict[str, dict[str, Any]] = {
        rtype: {
            "total": 0,
            "available": 0,
            "deployed": 0,
            "en_route": 0,
            "capacity": 0.0,
        }
        for rtype in RESOURCE_TYPES
    }
    total = 0
    for row in list_resources(session, limit=100000):
        bucket = by_type.setdefault(
            str(row.resource_type),
            {
                "total": 0,
                "available": 0,
                "deployed": 0,
                "en_route": 0,
                "capacity": 0.0,
            },
        )
        bucket["total"] += 1
        total += 1
        if row.status == "available":
            bucket["available"] += 1
        elif row.status == "deployed":
            bucket["deployed"] += 1
        elif row.status == "en_route":  # EM-031: committed but not on station
            bucket["en_route"] += 1
        bucket["capacity"] = round(bucket["capacity"] + float(row.capacity), 3)
    return {
        "total_resources": total,
        "available_resources": sum(b["available"] for b in by_type.values()),
        "by_type": by_type,
    }


def _normalize_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    """Rename/trim a raw CSV dict into canonical field names."""
    clean: dict[str, Any] = {}
    for raw_key, value in row.items():
        if raw_key is None:
            continue
        mapped = CSV_HEADER_ALIASES.get(_fold(raw_key))
        if mapped:
            clean[mapped] = value.strip() if isinstance(value, str) else value
    return clean


def parse_resource_csv(text: str) -> list[dict[str, Any]]:
    """Parse CSV text into validated row dicts (does not touch the database)."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise InventoryError("CSV has no header row")
    normalized_headers = {
        CSV_HEADER_ALIASES.get(_fold(name)) for name in reader.fieldnames
    }
    missing = [
        column for column in CSV_REQUIRED_COLUMNS if column not in normalized_headers
    ]
    if missing:
        raise InventoryError(f"CSV missing required column(s): {missing}")
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_CSV_ROWS:
            raise InventoryError(
                f"CSV exceeds the maximum of {MAX_CSV_ROWS} rows; split the import"
            )
        record = _normalize_csv_row(raw)
        if not _clean_str(record.get("resource_key")):
            raise InventoryError(f"row {line_no}: resource_key is required")
        rows.append(record)
    return rows


def import_resources_csv(session: Session, text: str) -> dict[str, Any]:
    """Bulk upsert resources from CSV; returns counts and per-row errors.

    Existing ``resource_key`` values are updated, new ones created. A row that
    fails validation is reported in ``errors`` and skipped without aborting the
    rest of the import.
    """
    rows = parse_resource_csv(text)
    created = 0
    updated = 0
    errors: list[dict[str, Any]] = []
    for index, record in enumerate(rows, start=2):
        try:
            key = str(record["resource_key"]).strip()
            if get_resource(session, key):
                changes = {k: v for k, v in record.items() if k != "resource_key"}
                update_resource(session, key, changes)
                updated += 1
            else:
                create_resource(session, record)
                created += 1
        except InventoryError as exc:
            errors.append({"row": index, "error": str(exc)})
    session.commit()
    return {
        "rows": len(rows),
        "created": created,
        "updated": updated,
        "skipped": len(errors),
        "errors": errors,
    }
