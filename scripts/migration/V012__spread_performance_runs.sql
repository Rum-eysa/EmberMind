-- V012: Spread performance benchmark runs for EM-022 (Epic E2)
-- Table: spread_performance_runs (before/after optimization timings for
-- the reference scenario, evidencing the 10-second recompute target)

CREATE TABLE IF NOT EXISTS spread_performance_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key VARCHAR(64) UNIQUE NOT NULL,
    scenario_key VARCHAR(64) NOT NULL DEFAULT 'reference_pilot',
    scenario_json TEXT NOT NULL DEFAULT '{}',
    baseline_json TEXT NOT NULL DEFAULT '{}',
    optimized_json TEXT NOT NULL DEFAULT '{}',
    baseline_total_ms FLOAT NOT NULL DEFAULT 0.0,
    optimized_total_ms FLOAT NOT NULL DEFAULT 0.0,
    speedup FLOAT NOT NULL DEFAULT 1.0,
    target_seconds FLOAT NOT NULL DEFAULT 10.0,
    target_met BOOLEAN NOT NULL DEFAULT 0,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_spread_perf_scenario ON spread_performance_runs (scenario_key);
