-- V014: Live-update change feed for EM-090 (Epic E9 — WebSocket live updates)
-- Table: live_updates — a monotonic log of operator-relevant changes (fire
-- events, spread forecasts and risk alerts) that the /ws/live endpoint streams
-- to connected clients without a page refresh. The autoincrement id doubles as
-- the sequence number so a reconnecting client can request only what it missed
-- (since=<id>).

CREATE TABLE IF NOT EXISTS live_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind VARCHAR(32) NOT NULL,
    event_key VARCHAR(64),
    title VARCHAR(200),
    message VARCHAR(500),
    payload_json TEXT,
    source VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_live_updates_kind ON live_updates (kind);
CREATE INDEX IF NOT EXISTS idx_live_updates_event_key ON live_updates (event_key);
CREATE INDEX IF NOT EXISTS idx_live_updates_kind_id ON live_updates (kind, id);
