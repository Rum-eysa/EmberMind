"""Save, list and share operator what-if scenarios (EM-059, Epic E6).

A thin CRUD + share-link layer over :class:`WhatIfScenario`. It stores the
*inputs* of a scenario (kind + the what-if request knobs) so a commander can
name a promising run, revisit it later and hand it to the team through a link.
Reproducing a scenario is the caller's job: replay ``params`` through the
existing ``/whatif/wind`` or ``/whatif/capacity`` endpoint, so results are never
stale and no physics is duplicated here.
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.scenario import SCENARIO_KINDS, WhatIfScenario

# Shared-link route the UI builds around a scenario's opaque token.
SHARE_PATH_PREFIX = "/api/v1/whatif/scenarios/by-token/"
_MAX_NAME_LEN = 120


class ScenarioError(RuntimeError):
    """Raised for an invalid scenario request (bad kind, empty name, missing)."""


def _new_key(prefix: str) -> str:
    """A short, URL-safe unique key (collision probability negligible)."""
    return f"{prefix}-{secrets.token_hex(6)}"


def _validate_params(kind: str, params: dict[str, Any]) -> None:
    """Reject params that cannot be replayed through the matching endpoint."""
    if not isinstance(params, dict):
        raise ScenarioError("params must be an object")
    if kind == "wind":
        if params.get("latitude") is None or params.get("longitude") is None:
            raise ScenarioError("wind scenario params need latitude and longitude")
    elif kind == "capacity":
        added = params.get("added_resources")
        if not isinstance(added, dict) or not added:
            raise ScenarioError("capacity scenario needs non-empty added_resources")


def create_scenario(
    session: Session,
    *,
    name: str,
    kind: str,
    params: dict[str, Any],
    event_key: str | None = None,
    created_by: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Persist a new named scenario from its what-if inputs."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ScenarioError("scenario name is required")
    if len(clean_name) > _MAX_NAME_LEN:
        raise ScenarioError(f"scenario name exceeds {_MAX_NAME_LEN} characters")
    if kind not in SCENARIO_KINDS:
        raise ScenarioError(f"unknown scenario kind: {kind!r}")
    _validate_params(kind, params)

    row = WhatIfScenario(
        scenario_key=_new_key("wsc"),
        name=clean_name,
        kind=kind,
        event_key=event_key,
        params_json=json.dumps(params, default=str),
        created_by=created_by,
        notes=notes,
    )
    session.add(row)
    session.flush()
    return row.as_dict


def list_scenarios(
    session: Session,
    kind: str | None = None,
    event_key: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return saved scenarios (newest first), optionally filtered."""
    query = select(WhatIfScenario).order_by(WhatIfScenario.id.desc())
    if kind:
        query = query.where(WhatIfScenario.kind == kind)
    if event_key:
        query = query.where(WhatIfScenario.event_key == event_key)
    rows = session.scalars(query.limit(max(1, int(limit)))).all()
    return [row.as_dict for row in rows]


def get_scenario(session: Session, scenario_key: str) -> dict[str, Any]:
    """Fetch one scenario by key, or raise :class:`ScenarioError`."""
    row = session.scalar(
        select(WhatIfScenario).where(WhatIfScenario.scenario_key == scenario_key)
    )
    if row is None:
        raise ScenarioError(f"scenario {scenario_key} not found")
    return row.as_dict


def get_by_share_token(session: Session, token: str) -> dict[str, Any]:
    """Fetch one published scenario by its share token (team hand-off)."""
    row = session.scalar(
        select(WhatIfScenario).where(WhatIfScenario.share_token == token)
    )
    if row is None:
        raise ScenarioError("share link is invalid or has been revoked")
    return row.as_dict


def rename_scenario(session: Session, scenario_key: str, name: str) -> dict[str, Any]:
    """Rename a saved scenario."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ScenarioError("scenario name is required")
    if len(clean_name) > _MAX_NAME_LEN:
        raise ScenarioError(f"scenario name exceeds {_MAX_NAME_LEN} characters")
    row = _row_or_raise(session, scenario_key)
    row.name = clean_name  # type: ignore[assignment]
    session.flush()
    return row.as_dict


def enable_share(session: Session, scenario_key: str) -> dict[str, Any]:
    """Publish a scenario for sharing: mint a token and return the link path."""
    row = _row_or_raise(session, scenario_key)
    if not row.share_token:
        row.share_token = secrets.token_urlsafe(16)  # type: ignore[assignment]
    session.flush()
    payload = row.as_dict
    payload["share_path"] = SHARE_PATH_PREFIX + str(row.share_token)
    return payload


def disable_share(session: Session, scenario_key: str) -> dict[str, Any]:
    """Revoke a scenario's share link (token cleared)."""
    row = _row_or_raise(session, scenario_key)
    row.share_token = None  # type: ignore[assignment]
    session.flush()
    return row.as_dict


def delete_scenario(session: Session, scenario_key: str) -> bool:
    """Delete a scenario; return whether a row was removed."""
    row = session.scalar(
        select(WhatIfScenario).where(WhatIfScenario.scenario_key == scenario_key)
    )
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def _row_or_raise(session: Session, scenario_key: str) -> WhatIfScenario:
    """Internal: load a scenario ORM row or raise for a missing key."""
    row = session.scalar(
        select(WhatIfScenario).where(WhatIfScenario.scenario_key == scenario_key)
    )
    if row is None:
        raise ScenarioError(f"scenario {scenario_key} not found")
    return row
