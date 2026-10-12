-- V032: Per-region silent-zone sensitivity + min-silence tuning (EM-044, Epic E4)
-- Table: silent_zone_tuning.
-- Stores one override row per silent region for the two operator-owned knobs:
-- the silence z-score threshold (EM-035 semantics) and the minimum silence
-- duration (hours) before EM-040 raises an alert. A NULL column means "inherit
-- the global default", so reset-to-default clears the value (or drops the row).
-- The who/when/old->new of every change is recorded in the unified audit_trail
-- ledger under the "threshold" domain, not in this table.

CREATE TABLE IF NOT EXISTS silent_zone_tuning (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tuning_key VARCHAR(64) NOT NULL UNIQUE,
    region_id INTEGER NOT NULL UNIQUE,
    sensitivity_z FLOAT,
    min_silence_hours FLOAT,
    updated_by VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_silent_zone_tuning_tuning_key
    ON silent_zone_tuning (tuning_key);
CREATE INDEX IF NOT EXISTS ix_silent_zone_tuning_region_id
    ON silent_zone_tuning (region_id);
