"""Shift-handover notes and one-click summary endpoints (EM-089, Epic E8).

Adds / lists / deletes free-text operator notes against an incident and exposes
the read-time handover summary that merges those notes with the chronological
event stream (EM-081) and the multi-fire roster (EM-082).
"""
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.shift_handover import (
    ShiftHandoverError,
    add_note,
    delete_note,
    get_note,
    handover_config,
    handover_summary,
    list_notes,
)


class NoteRequest(BaseModel):
    """A free-text note to attach to one incident."""

    event_key: str
    body: str
    author: Optional[str] = None


def _http_error(exc: ShiftHandoverError) -> HTTPException:
    """Map a service error to the right HTTP status (missing vs invalid)."""
    text = str(exc)
    status = 404 if ("bulunamadı" in text or "not found" in text) else 400
    return HTTPException(status_code=status, detail={"status": "error", "error": text})


def register_shift_handover_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-089 shift-handover endpoints."""

    @api.get("/api/v1/shift-handover/config", tags=["panel"])
    def shift_handover_config() -> dict[str, Any]:
        """Note category, sources and the page-size bound."""
        return handover_config(settings)

    @api.get("/api/v1/shift-handover", tags=["panel"])
    def shift_handover_feed(
        event_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """One-click handover summary (optional single-incident scope)."""
        with database.session() as session:
            return handover_summary(session, settings, event_key=event_key)

    @api.get("/api/v1/shift-handover/notes", tags=["panel"])
    def shift_handover_notes_list(
        event_key: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        """Operator notes, newest-first, optionally scoped to one incident."""
        with database.session() as session:
            return list_notes(session, settings, event_key=event_key, limit=limit)

    @api.post("/api/v1/shift-handover/notes", tags=["panel"])
    def shift_handover_note_add(req: NoteRequest) -> dict[str, Any]:
        """Attach a free-text note to an incident."""
        try:
            with database.session() as session:
                result = add_note(
                    session,
                    settings,
                    event_key=req.event_key,
                    body=req.body,
                    author=req.author,
                )
                session.commit()
        except ShiftHandoverError as exc:
            raise _http_error(exc) from exc
        return {"status": "created", **result}

    @api.get("/api/v1/shift-handover/notes/{note_id}", tags=["panel"])
    def shift_handover_note_get(note_id: int) -> dict[str, Any]:
        """Fetch a single note by id."""
        try:
            with database.session() as session:
                return get_note(session, note_id)
        except ShiftHandoverError as exc:
            raise _http_error(exc) from exc

    @api.delete("/api/v1/shift-handover/notes/{note_id}", tags=["panel"])
    def shift_handover_note_delete(note_id: int) -> dict[str, Any]:
        """Delete one note."""
        try:
            with database.session() as session:
                result = delete_note(session, note_id)
                session.commit()
        except ShiftHandoverError as exc:
            raise _http_error(exc) from exc
        return {"status": "deleted", **result}
