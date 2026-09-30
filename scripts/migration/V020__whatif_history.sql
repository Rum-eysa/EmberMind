-- V020: Rolling what-if run history for EM-062 (Epic E6)
-- Table: whatif_history (auto-captured runs, trimmed to the last N rows).
-- Records each what-if run so the operator can scroll back through what they
-- just tried and revert to any entry in one click. Results are still replayed
-- live through the existing what-if endpoints, never cached here.

CREATE TABLE IF NOT EXISTS whatif_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key VARCHAR(64),
    kind VARCHAR(16) NOT NULL DEFAULT 'wind',
    label VARCHAR(120),
    params_json TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_whatif_history_event ON whatif_history (event_key);
CREATE INDEX IF NOT EXISTS idx_whatif_history_created ON whatif_history (id);
