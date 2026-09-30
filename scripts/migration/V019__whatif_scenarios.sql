-- V019: Saved/shareable operator what-if scenarios for EM-059 (Epic E6)
-- Table: whatif_scenarios (named what-if inputs + optional share token).
-- Stores only the scenario *inputs* (kind + params_json). A fresh result is
-- always replayed through the existing what-if endpoints, never cached here.

CREATE TABLE IF NOT EXISTS whatif_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_key VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(120) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    event_key VARCHAR(64),
    params_json TEXT NOT NULL,
    share_token VARCHAR(64) UNIQUE,
    created_by VARCHAR(64),
    notes VARCHAR(255),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_whatif_scenarios_kind ON whatif_scenarios (kind);
CREATE INDEX IF NOT EXISTS idx_whatif_scenarios_event ON whatif_scenarios (event_key);
CREATE INDEX IF NOT EXISTS idx_whatif_scenarios_token ON whatif_scenarios (share_token);
