"""Shared HTTP-layer helpers reused across route modules.

Extracted during the code-quality audit (MEDIUM, behaviour-neutral DRY): the
``as_of`` query-parameter parser was byte-identical in four route modules
(``isolation_forest_anomaly``, ``signal_baseline``, ``signal_baseline_seasonal``
and ``silent_zone_confidence``). Consolidating it here keeps a single source of
truth; the modules import it under the original ``_parse_as_of`` name so their
call sites are unchanged. It lives beside the routes (not in ``src/utils``)
because, unlike the pure time helpers there, it raises a FastAPI
``HTTPException``.
"""
from datetime import date

from fastapi import HTTPException


def parse_as_of(value: str | None) -> date | None:
    """Parse an optional ``as_of`` query parameter (``YYYY-MM-DD``) into a date.

    Returns ``None`` for an absent value and raises a 400 on a malformed one,
    so every endpoint that accepts ``as_of`` describes the failure the same way.
    """
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error": "as_of YYYY-MM-DD biçiminde olmalı"},
        ) from exc
