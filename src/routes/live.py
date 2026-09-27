"""WebSocket live-update feed and its polling fallback (EM-090).

Connected operator clients receive fire-event, forecast and alert changes
without a page refresh. The transport is deliberately simple and robust:

* the database change feed is the single source of truth, so updates written
  by a separate Celery worker process still reach every client;
* each connection polls the feed on a short interval and only pushes frames
  for changes newer than the cursor it has already delivered;
* a client passes the last id it saw as ``?since=<id>`` (query string) so a
  reconnect transparently replays whatever it missed during the outage.
"""
import asyncio
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from src.database import Database
from src.services.live import feed


def _parse_since(websocket: WebSocket) -> int:
    """Read the reconnect cursor from the query string, defaulting to 0."""
    raw = websocket.query_params.get("since", "0")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def register_live_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the WebSocket live feed and the equivalent REST polling route."""
    poll_interval = float(getattr(settings, "LIVE_POLL_INTERVAL_SECONDS", 2.0))
    heartbeat = float(getattr(settings, "LIVE_HEARTBEAT_SECONDS", 15.0))

    async def _read(since: int) -> dict[str, Any]:
        def _sync_read() -> dict[str, Any]:
            with database.session() as session:
                return feed(session, settings, since)

        return await run_in_threadpool(_sync_read)

    @api.get("/api/v1/live/updates", tags=["live"])
    def live_updates(since: int = Query(default=0, ge=0)) -> dict[str, Any]:
        """Polling fallback: feed entries newer than ``since`` plus a cursor."""
        with database.session() as session:
            return feed(session, settings, since)

    @api.websocket("/ws/live")
    async def live_websocket(websocket: WebSocket) -> None:
        """Stream the change feed to one client until it disconnects."""
        await websocket.accept()
        last_id = _parse_since(websocket)
        try:
            snapshot = await _read(last_id)
            await websocket.send_json({"type": "snapshot", **snapshot})
            last_id = snapshot["last_id"]
            idle = 0.0
            while True:
                # A short receive doubles as the disconnect detector: it raises
                # WebSocketDisconnect the moment the peer goes away, and simply
                # times out while the connection is idle so we can poll next.
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(), timeout=poll_interval
                    )
                    continue  # a client message arrived; re-arm the wait
                except asyncio.TimeoutError:
                    pass
                idle += poll_interval
                batch = await _read(last_id)
                if batch["updates"]:
                    await websocket.send_json({"type": "update", **batch})
                    last_id = batch["last_id"]
                    idle = 0.0
                elif heartbeat and idle >= heartbeat:
                    await websocket.send_json({"type": "ping", "last_id": last_id})
                    idle = 0.0
        except WebSocketDisconnect:
            return
        except (RuntimeError, OSError):
            # The peer vanished mid-send; nothing to report.
            return
