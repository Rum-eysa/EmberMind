"""Chronological operator event timeline endpoints (EM-081, Epic E8).

Read-only projection merging the live change feed (EM-090) and operator-accepted
recommendations (EM-047) into one newest-first stream for shift handover. Nothing
new is persisted.
"""
from typing import Any

from fastapi import FastAPI, Query

from src.database import Database
from src.services.event_timeline import event_timeline, timeline_config


def register_event_timeline_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-081 event timeline feed."""

    @api.get("/api/v1/event-timeline/config", tags=["panel"])
    def event_timeline_config() -> dict[str, Any]:
        """Categories, labels, sources and the merge/ordering contract."""
        return timeline_config(settings)

    @api.get("/api/v1/event-timeline", tags=["panel"])
    def event_timeline_feed(
        event_key: str | None = Query(default=None),
        category: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        """Merged chronological event stream (optional filters + page size)."""
        with database.session() as session:
            return event_timeline(
                session,
                settings,
                event_key=event_key,
                category=category,
                limit=limit,
            )
