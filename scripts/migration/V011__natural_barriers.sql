-- V011: Natural barriers / land-sea mask for EM-021 (Epic E2)
-- Table: natural_barriers (water bodies excluded from spread, partial
-- obstacles modelled with a slowdown coefficient)

CREATE TABLE IF NOT EXISTS natural_barriers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    barrier_key VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    barrier_type VARCHAR(32) NOT NULL,
    geometry_wkt TEXT NOT NULL,
    slowdown_factor FLOAT NOT NULL DEFAULT 0.0,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    source VARCHAR(64) NOT NULL DEFAULT 'operator',
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_natural_barriers_active ON natural_barriers (is_active);
CREATE INDEX IF NOT EXISTS idx_natural_barriers_type ON natural_barriers (barrier_type);
