-- V027: Free-text operator notes on a fire event (EM-089, Epic E8)
-- Table: event_notes.
--
-- The live change feed (EM-090), the accepted recommendations (EM-047) and the
-- read-time timeline (EM-081) are all machine-generated. None lets the operator
-- type a note against an incident and have it survive the shift, and none can
-- produce the one-click handover summary EM-089 asks for.
--
-- ``event_notes`` stores only the human commentary - one free-text row per
-- note, keyed to an incident's event_key and stamped with who wrote it. The
-- fire status / risk band / resource roster stay in their own tables and are
-- composed into the handover summary at read time. Purely additive.

CREATE TABLE IF NOT EXISTS event_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key VARCHAR(64) NOT NULL,
    body TEXT NOT NULL,
    author VARCHAR(128),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_event_notes_event_key
    ON event_notes (event_key);
