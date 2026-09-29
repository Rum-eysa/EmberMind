-- V016: Capacity unit assumptions for EM-028 (Epic E3 — capacity & risk index)
-- Table: capacity_assumptions — one row per deployable resource type holding
-- the admin-editable "effective suppression capacity" (hectare/hour) assumed
-- for a single unit of that type. Normalising every resource to a common
-- ha/hour unit lets capacity and risk share one unit so the gap index is
-- meaningful. Rows are seeded from config defaults and edited at runtime.

CREATE TABLE IF NOT EXISTS capacity_assumptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type VARCHAR(32) UNIQUE NOT NULL,
    ha_per_hour FLOAT NOT NULL DEFAULT 0.0,
    updated_by VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_capacity_assumptions_type ON capacity_assumptions (resource_type);
