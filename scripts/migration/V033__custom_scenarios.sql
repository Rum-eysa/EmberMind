-- V033: UI-authored custom demo scenarios (EM-108, Epic E11)
-- Table: custom_scenarios.
-- Stores one authored scenario *definition* per row: a slug key, a display
-- title, a deterministic seed and the *normalized* (EM-104 validated) scenario
-- config as canonical JSON. Launching a custom scenario reuses the EM-104 and
-- EM-105 path (build_dataset + persist_dataset + a ScenarioRun audit row stamped
-- preset=custom:<key>). No operational row lives in this table. The config is
-- stored post-normalization so an activation stays byte-reproducible and does not
-- drift if DEFAULT_CONFIG changes later.

CREATE TABLE IF NOT EXISTS custom_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_key VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(160) NOT NULL,
    description TEXT,
    seed INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    archetype VARCHAR(48) NOT NULL DEFAULT 'custom',
    created_by VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_custom_scenarios_scenario_key
    ON custom_scenarios (scenario_key);
