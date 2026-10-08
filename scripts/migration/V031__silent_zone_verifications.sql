-- V031: Operator verification workflow for silent-region alerts (EM-041, Epic E4)
-- Table: silent_zone_verifications.
-- Persists each operator verdict (verified / false alarm / under review) on an
-- EM-040 high-priority silent-region alert. Every marking is an append-only
-- audit row - a prior verdict is never overwritten - so the detector can be
-- tuned against real outcomes over time and the "who judged what, and why"
-- chain stays reconstructable.

CREATE TABLE IF NOT EXISTS silent_zone_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_key VARCHAR(64) NOT NULL UNIQUE,
    region_id INTEGER NOT NULL,
    region_name VARCHAR(128),
    status VARCHAR(16) NOT NULL,
    reason VARCHAR(255),
    verified_by VARCHAR(64),
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_silent_zone_verifications_verification_key
    ON silent_zone_verifications (verification_key);
CREATE INDEX IF NOT EXISTS ix_silent_zone_verifications_region_id
    ON silent_zone_verifications (region_id);
CREATE INDEX IF NOT EXISTS ix_silent_zone_verifications_status
    ON silent_zone_verifications (status);
CREATE INDEX IF NOT EXISTS idx_silent_verif_region_created
    ON silent_zone_verifications (region_id, id);
CREATE INDEX IF NOT EXISTS idx_silent_verif_status
    ON silent_zone_verifications (status, id);
