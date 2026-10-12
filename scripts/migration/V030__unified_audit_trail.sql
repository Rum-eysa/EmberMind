-- V030: Unified immutable audit ledger (EM-096, Epic E10)
-- Table: audit_trail.
--
-- Earlier epics recorded accountability per feature in unrelated tables
-- (capacity_assumption_audit for EM-034, recommendation_decisions for EM-047,
-- share policies and webhook deliveries for their own epics). EM-096 asks for a
-- single cross-domain trail of who made which decision, when, and how, where
-- the records cannot be deleted.
--
-- One append-only row per governance-relevant action. The service layer exposes
-- only record / list / config (no update, no delete), so immutability holds at
-- the application seam. Purely additive - existing per-feature audits are kept.

CREATE TABLE IF NOT EXISTS audit_trail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_key VARCHAR(64) NOT NULL UNIQUE,
    domain VARCHAR(32) NOT NULL,
    action VARCHAR(48) NOT NULL,
    subject_key VARCHAR(96),
    actor VARCHAR(64) NOT NULL,
    summary VARCHAR(255) NOT NULL DEFAULT '',
    old_value_json TEXT NOT NULL DEFAULT 'null',
    new_value_json TEXT NOT NULL DEFAULT 'null',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_audit_trail_domain ON audit_trail (domain);
CREATE INDEX IF NOT EXISTS ix_audit_trail_action ON audit_trail (action);
CREATE INDEX IF NOT EXISTS ix_audit_trail_actor ON audit_trail (actor);
CREATE INDEX IF NOT EXISTS ix_audit_trail_subject_key ON audit_trail (subject_key);
CREATE INDEX IF NOT EXISTS idx_audit_trail_domain_created
    ON audit_trail (domain, id);
CREATE INDEX IF NOT EXISTS idx_audit_trail_actor_created
    ON audit_trail (actor, id);
