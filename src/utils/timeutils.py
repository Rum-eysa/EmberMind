"""Shared datetime helpers for consistent UTC handling and serialization.

Timestamps are persisted as naive UTC datetimes and serialized as ISO-8601
strings with a trailing ``Z`` so every API response describes time the same way.
"""
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime, suitable for storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_iso(value: Any) -> str | None:
    """Serialize a naive UTC datetime to an ISO-8601 string with a ``Z`` suffix.

    Accepts ``Any`` so it can be called directly with SQLAlchemy ``Column``
    attributes on model instances, mirroring the previous inline
    ``value.isoformat() + "Z"`` expressions.
    """
    return value.isoformat() + "Z" if value is not None else None
