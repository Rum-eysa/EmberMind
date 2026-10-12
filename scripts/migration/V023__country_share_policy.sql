-- V023: Country / role data-sharing policy (EM-070, Epic E7)
-- Table: country_share_policy.
-- Append-only authorization policy: an administrator controls which field
-- groups (fire / risk / support) an owner country exposes to the partner side,
-- per role scope ("*" is the per-country default). Each change inserts a new
-- row carrying the value it replaced, so the newest row per (country, role) is
-- the effective policy and the full series is the audit trail. Purely additive.

CREATE TABLE IF NOT EXISTS country_share_policy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key VARCHAR(64) NOT NULL UNIQUE,
    viewer_country VARCHAR(2) NOT NULL,
    role VARCHAR(48) NOT NULL DEFAULT '*',
    shared_fields VARCHAR(64) NOT NULL,
    previous_shared_fields VARCHAR(64),
    changed_by VARCHAR(64),
    reason VARCHAR(255),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_country_share_policy_policy_key
    ON country_share_policy (policy_key);
CREATE INDEX IF NOT EXISTS ix_country_share_policy_viewer_country
    ON country_share_policy (viewer_country);
CREATE INDEX IF NOT EXISTS ix_country_share_policy_role
    ON country_share_policy (role);
CREATE INDEX IF NOT EXISTS idx_share_policy_country_role
    ON country_share_policy (viewer_country, role, id);
