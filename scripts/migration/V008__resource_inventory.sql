-- V008: Suppression resource inventory schema for EM-103 (Epic E11)
-- Table: suppression_resources (crew / helicopter / uav assets with capacity)

CREATE TABLE IF NOT EXISTS suppression_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_key VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    resource_type VARCHAR(32) NOT NULL DEFAULT 'crew',
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    base_key VARCHAR(64),
    country VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'available',
    capacity FLOAT NOT NULL DEFAULT 0.0,
    capacity_unit VARCHAR(24),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_suppression_resources_key ON suppression_resources (resource_key);
CREATE INDEX IF NOT EXISTS idx_suppression_resources_base ON suppression_resources (base_key);
CREATE INDEX IF NOT EXISTS idx_suppression_resources_type_status ON suppression_resources (resource_type, status);
CREATE INDEX IF NOT EXISTS idx_suppression_resources_coords ON suppression_resources (latitude, longitude);
