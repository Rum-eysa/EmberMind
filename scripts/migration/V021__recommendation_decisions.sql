-- V021: Operator decision audit for positioning proposals (EM-047, Epic E5)
-- Table: recommendation_decisions.
-- Persists each accept / reject / edit call the operator makes on an EM-052
-- proposal. Accepting or editing commits the resource to the en_route status
-- while rejecting records an optional reason, and every call leaves an
-- immutable audit row so the final decision always stays with the operator.

CREATE TABLE IF NOT EXISTS recommendation_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_key VARCHAR(64) NOT NULL UNIQUE,
    event_key VARCHAR(64),
    proposal_id VARCHAR(96),
    resource_key VARCHAR(64) NOT NULL,
    action VARCHAR(16) NOT NULL,
    reason VARCHAR(255),
    decided_by VARCHAR(64),
    detail_json TEXT NOT NULL DEFAULT '{}',
    resource_status_before VARCHAR(32),
    resource_status_after VARCHAR(32),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_recommendation_decisions_decision_key
    ON recommendation_decisions (decision_key);
CREATE INDEX IF NOT EXISTS ix_recommendation_decisions_event_key
    ON recommendation_decisions (event_key);
CREATE INDEX IF NOT EXISTS ix_recommendation_decisions_resource_key
    ON recommendation_decisions (resource_key);
CREATE INDEX IF NOT EXISTS ix_recommendation_decisions_action
    ON recommendation_decisions (action);
CREATE INDEX IF NOT EXISTS idx_rec_decisions_event_created
    ON recommendation_decisions (event_key, id);
CREATE INDEX IF NOT EXISTS idx_rec_decisions_resource
    ON recommendation_decisions (resource_key, id);
