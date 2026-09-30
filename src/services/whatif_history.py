"""Rolling what-if run history + one-click revert (EM-062, Epic E6).

Every ephemeral what-if run the operator performs is captured automatically
into a short, self-trimming history so they can scroll back through the last
few attempts and jump to any one of them without re-typing the knobs. This is
distinct from :mod:`src.services.scenario_share` (EM-059), which stores only
*deliberately named* scenarios that survive until deleted; a history row is
cheap, automatic and bounded to the most recent ``WHATIF_HISTORY_LIMIT`` runs.

As with EM-059, only the run *inputs* are stored. Reverting replays them
through the existing ``/whatif/wind`` (or ``/whatif/capacity``) endpoint, so no
physics is duplicated and no result is ever stale.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.models.scenario import WhatIfHistory


class HistoryError(RuntimeError):
    """Raised when a history entry cannot be found."""


def _latest(session: Session, event_key: str | None) -> WhatIfHistory | None:
    """The most recent history row (optionally scoped to one event)."""
    query = select(WhatIfHistory).order_by(WhatIfHistory.id.desc()).limit(1)
    if event_key:
        query = query.where(WhatIfHistory.event_key == event_key)
    return session.scalars(query).first()


def record_history(
    session: Session,
    *,
    enabled: bool,
    limit: int,
    params: dict[str, Any],
    kind: str = "wind",
    event_key: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Capture a what-if run, skip an exact repeat, and trim to the last ``limit``.

    Returns a small summary (``recorded`` / ``count`` / ``dropped``) so the
    caller (the operator map) can refresh the list without a second round-trip.
    """
    if not enabled:
        return {"recorded": False, "reason": "disabled", "count": 0, "dropped": 0}

    params_json = json.dumps(params, default=str, sort_keys=True)
    previous = _latest(session, event_key)
    if previous is not None and str(previous.params_json) == params_json:
        # Debounce identical re-runs (slider released twice, focus churn, ...).
        return {
            "recorded": False,
            "reason": "duplicate",
            "count": _count(session),
            "dropped": 0,
            "entry": previous.as_dict,
        }

    row = WhatIfHistory(
        event_key=event_key,
        kind=kind,
        label=label,
        params_json=params_json,
    )
    session.add(row)
    session.flush()

    keep = max(1, int(limit))
    dropped = _trim(session, keep)
    return {
        "recorded": True,
        "count": _count(session),
        "dropped": dropped,
        "entry": row.as_dict,
    }


def _trim(session: Session, keep: int) -> int:
    """Delete all but the newest ``keep`` rows; return how many were dropped."""
    ids = session.scalars(
        select(WhatIfHistory.id).order_by(WhatIfHistory.id.desc())
    ).all()
    if len(ids) <= keep:
        return 0
    drop_ids = list(ids[keep:])
    session.execute(delete(WhatIfHistory).where(WhatIfHistory.id.in_(drop_ids)))
    session.flush()
    return len(drop_ids)


def _count(session: Session) -> int:
    """Current number of retained history rows."""
    return len(session.scalars(select(WhatIfHistory.id)).all())


def list_history(
    session: Session,
    *,
    event_key: str | None = None,
    kind: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return retained history newest-first, optionally filtered."""
    query = select(WhatIfHistory).order_by(WhatIfHistory.id.desc())
    if event_key:
        query = query.where(WhatIfHistory.event_key == event_key)
    if kind:
        query = query.where(WhatIfHistory.kind == kind)
    rows = session.scalars(query.limit(max(1, int(limit)))).all()
    return [row.as_dict for row in rows]


def get_history(session: Session, history_id: int) -> dict[str, Any]:
    """Fetch one history entry (for revert) or raise :class:`HistoryError`."""
    row = session.get(WhatIfHistory, int(history_id))
    if row is None:
        raise HistoryError(f"history entry {history_id} not found")
    return row.as_dict


def clear_history(session: Session, *, event_key: str | None = None) -> int:
    """Drop history (all rows, or one event's rows); return rows removed."""
    rows = session.scalars(
        select(WhatIfHistory.id)
        if not event_key
        else select(WhatIfHistory.id).where(WhatIfHistory.event_key == event_key)
    ).all()
    if not rows:
        return 0
    session.execute(delete(WhatIfHistory).where(WhatIfHistory.id.in_(list(rows))))
    session.flush()
    return len(rows)
