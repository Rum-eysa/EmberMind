-- V017: Recompute latency telemetry for EM-060 (Epic E6 — performance budget)
-- Table: recompute_latency_samples — one append-only row per spread/what-if
-- recomputation capturing wall-clock duration (ms), the resolution it ran at
-- (fine / coarse), the operator budget in force (seconds) and whether the
-- rolling p95 was over budget once the row landed. The p95 recompute-latency
-- budget and the automatic coarse-resolution scale-down are measured over the
-- most recent rows of this log.

CREATE TABLE IF NOT EXISTS recompute_latency_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source VARCHAR(64) NOT NULL DEFAULT 'recompute',
    latency_ms FLOAT NOT NULL DEFAULT 0.0,
    target_seconds FLOAT NOT NULL DEFAULT 10.0,
    resolution VARCHAR(16) NOT NULL DEFAULT 'fine',
    breached BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_recompute_latency_source ON recompute_latency_samples (source);
CREATE INDEX IF NOT EXISTS idx_recompute_latency_created ON recompute_latency_samples (created_at);
