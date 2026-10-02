-- V028: Audit trail for capacity unit assumption edits (EM-034, Epic E3)
-- Table: capacity_assumption_audit.
--
-- EM-028 made the per-resource-type ha/hour assumption editable at runtime but
-- only stored the latest editor in a single updated_by column - there was no
-- durable record of the previous value, who changed it, or when. EM-034's
-- acceptance criterion "değişiklik denetim kaydına yazılır" requires a history.
--
-- One append-only row per applied change (a value that actually differs from
-- the stored one). The live assumptions stay in capacity_assumptions. This
-- table only records the transition and is purely additive.

CREATE TABLE IF NOT EXISTS capacity_assumption_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type VARCHAR(32) NOT NULL,
    old_value FLOAT NOT NULL DEFAULT 0.0,
    new_value FLOAT NOT NULL DEFAULT 0.0,
    updated_by VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_capacity_assumption_audit_resource_type
    ON capacity_assumption_audit (resource_type);
