-- V009: Synthetic scenario generation runs for EM-104 (Epic E11)
-- Table: scenario_runs (audit trail: seed/config/result hashes, labels)

CREATE TABLE IF NOT EXISTS scenario_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key VARCHAR(64) UNIQUE NOT NULL,
    scenario_tag VARCHAR(32) NOT NULL,
    seed INTEGER NOT NULL,
    preset VARCHAR(64),
    config_hash VARCHAR(64) NOT NULL,
    result_hash VARCHAR(64) NOT NULL,
    base_time FLOAT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    persisted INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    dataset_json TEXT NOT NULL,
    generated_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scenario_runs_tag ON scenario_runs (scenario_tag);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_seed ON scenario_runs (seed);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_generated ON scenario_runs (generated_at);
