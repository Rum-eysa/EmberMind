"""Manual fire-event mutation endpoints (update and delete a fire event).

Extracted from the create_fastapi_app monolith (code-quality audit A-6, step 4)
into the project's standard ``register_*_routes`` module. Behaviour-preserving:
the ``ManualFireEventUpdateRequest`` model and both route bodies are moved
verbatim; the same PUT/DELETE routes are registered in the same order via the
single ``register_event_lifecycle_routes`` call placed exactly where the inline
block used to sit (after the grid/pipeline registration), so route registration
order (and thus the OpenAPI surface) is unchanged. This is the last inline
domain left in the factory; the read/create event endpoints already live in
``src/routes/spatial_events.py``.
"""
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from src.database import Database
from src.models.spatial import FireEvent, FireForecast
from src.services.manual_fire_event import VALID_SEVERITIES, VALID_STATUSES

_LOG = logging.getLogger(__name__)


class ManualFireEventUpdateRequest(BaseModel):
    """Request payload for updating a manual fire event."""

    name: str | None = None
    severity: str | None = None
    status: str | None = None
    notes: str | None = None


def register_event_lifecycle_routes(
    api: FastAPI, database: Database, _settings: Any
) -> None:
    """Attach the manual fire-event update and delete endpoints.

    ``_settings`` is unused here (both handlers only need ``database``); it is
    underscore-prefixed to keep the project-wide ``register_*_routes`` signature
    while satisfying pylint's unused-argument check.
    """

    @api.put(
        "/api/v1/events/{event_key}",
        tags=["events"],
    )
    def update_manual_event(
        event_key: str,
        req: ManualFireEventUpdateRequest,
    ) -> dict[str, Any]:
        """Update an existing fire event."""
        try:
            with database.session() as session:
                event = session.scalar(
                    select(FireEvent).where(FireEvent.event_key == event_key)
                )

                if not event:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "status": "not_found",
                            "error": f"Event {event_key} not found",
                        },
                    )

                # Update fields if provided (controlled vocabularies enforced)
                if req.name is not None:
                    event.name = req.name  # type: ignore[assignment]
                if req.severity is not None:
                    if req.severity not in VALID_SEVERITIES:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "status": "error",
                                "error": (
                                    f"invalid severity '{req.severity}'; "
                                    f"expected one of {list(VALID_SEVERITIES)}"
                                ),
                            },
                        )
                    event.severity = req.severity  # type: ignore[assignment]
                if req.status is not None:
                    if req.status not in VALID_STATUSES:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "status": "error",
                                "error": (
                                    f"invalid status '{req.status}'; "
                                    f"expected one of {list(VALID_STATUSES)}"
                                ),
                            },
                        )
                    event.status = req.status  # type: ignore[assignment]
                if req.notes is not None:
                    event.notes = req.notes  # type: ignore[assignment]

                session.flush()

                return {
                    "status": "updated",
                    "event": event.as_dict,
                }
        except HTTPException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            _LOG.exception("failed to update fire event %s", event_key)
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "error",
                    "error": "internal server error while updating event",
                },
            ) from exc

    @api.delete(
        "/api/v1/events/{event_key}",
        tags=["events"],
    )
    def delete_manual_event(event_key: str) -> dict[str, Any]:
        """Delete a fire event."""
        try:
            with database.session() as session:
                event = session.scalar(
                    select(FireEvent).where(FireEvent.event_key == event_key)
                )

                if not event:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "status": "not_found",
                            "error": f"Event {event_key} not found",
                        },
                    )

                # App-level cascade: stored forecasts belong to this event and
                # must not outlive it as orphans.
                session.execute(
                    delete(FireForecast).where(FireForecast.event_key == event_key)
                )
                session.delete(event)

                return {
                    "status": "deleted",
                    "event_key": event_key,
                }
        except HTTPException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            _LOG.exception("failed to delete fire event %s", event_key)
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "error",
                    "error": "internal server error while deleting event",
                },
            ) from exc
