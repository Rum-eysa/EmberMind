"""Live-update change feed service (EM-090).

Writes operator-relevant changes (fire events, spread forecasts, risk alerts)
to a monotonic feed and reads them back for the WebSocket stream and the
polling fallback. The database is the single source of truth, so updates
produced by a separate Celery worker process still reach connected clients.

Recording is best-effort: a live-feed failure must never break the pipeline or
endpoint that triggered it, so callers may wrap :func:`record_update` in a
try/except. The function itself is a no-op when the feature is disabled.
"""
import json
import logging
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.live import LIVE_KINDS, LiveUpdate

_LOG = logging.getLogger(__name__)


class LiveError(Exception):
    """Raised for an invalid live-update request (e.g. an unknown kind)."""


def record_update(
    session: Session,
    settings: Any,
    kind: str,
    *,
    event_key: Optional[str] = None,
    title: Optional[str] = None,
    message: Optional[str] = None,
    payload: Any = None,
    source: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Append one entry to the live change feed and return it as a dict.

    Returns ``None`` when live updates are disabled by configuration. Raises
    :class:`LiveError` for an unknown ``kind`` so programming mistakes surface
    loudly instead of silently writing an unusable row.
    """
    if not getattr(settings, "LIVE_UPDATES_ENABLED", True):
        return None
    if kind not in LIVE_KINDS:
        raise LiveError(f"unknown live update kind: {kind!r}")
    row = LiveUpdate(
        kind=kind,
        event_key=event_key,
        title=title,
        message=message,
        source=source,
        payload_json=json.dumps(payload, default=str) if payload is not None else None,
    )
    session.add(row)
    session.flush()
    return row.as_dict


def recent_updates(
    session: Session, since_id: int = 0, limit: int = 100
) -> list[dict[str, Any]]:
    """Return feed entries with ``id > since_id``, oldest first (catch-up)."""
    rows = session.scalars(
        select(LiveUpdate)
        .where(LiveUpdate.id > since_id)
        .order_by(LiveUpdate.id.asc())
        .limit(limit)
    ).all()
    return [row.as_dict for row in rows]


def latest_id(session: Session) -> int:
    """Return the highest feed id currently stored (0 when empty)."""
    # pylint: disable=not-callable  # SQLAlchemy ``func`` is dynamic (false positive).
    return int(session.scalar(select(func.max(LiveUpdate.id))) or 0)


def feed(session: Session, settings: Any, since_id: int = 0) -> dict[str, Any]:
    """Build a catch-up frame: the updates after ``since_id`` plus the cursor.

    ``last_id`` is the cursor a client should send back on its next request so
    it never re-reads or misses a change (reconnect compensation).
    """
    limit = int(getattr(settings, "LIVE_MAX_CATCHUP", 100))
    updates = recent_updates(session, since_id, limit)
    last_id = updates[-1]["id"] if updates else int(since_id)
    return {"last_id": last_id, "count": len(updates), "updates": updates}


def safe_record_update(
    session: Session,
    settings: Any,
    kind: str,
    *,
    event_key: Optional[str] = None,
    title: Optional[str] = None,
    message: Optional[str] = None,
    payload: Any = None,
    source: Optional[str] = None,
) -> None:
    """Best-effort :func:`record_update` for pipeline/endpoint call sites.

    A live-feed hiccup must never roll back or fail the change that triggered
    it, so any error is logged and swallowed here.
    """
    try:
        record_update(
            session,
            settings,
            kind,
            event_key=event_key,
            title=title,
            message=message,
            payload=payload,
            source=source,
        )
    except Exception:  # pylint: disable=broad-except
        _LOG.exception("live feed: failed to record %r update", kind)
