-- V024: Joint cross-border early-warning notification (EM-069, Epic E7)
-- Table: crossborder_notification.
-- Turns the EM-067 border-crossing projection into an action: when a fire's
-- crossing likelihood and lead time cross the agreed threshold, a pre-defined
-- coordination channel to the partner country is dispatched and recorded here.
-- Edge-triggered (one open row per event/target) so recompute never spams the
-- neighbour. The open to resolved lifecycle keeps an auditable trail of what
-- was actually sent. Purely additive.

CREATE TABLE IF NOT EXISTS crossborder_notification (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_key VARCHAR(64) NOT NULL UNIQUE,
    event_key VARCHAR(64) NOT NULL,
    source_country VARCHAR(2) NOT NULL,
    target_country VARCHAR(2) NOT NULL,
    likelihood DOUBLE PRECISION NOT NULL,
    likelihood_level VARCHAR(16) NOT NULL,
    crossing_minutes DOUBLE PRECISION,
    within_forecast_window INTEGER NOT NULL DEFAULT 0,
    channel VARCHAR(64) NOT NULL,
    recipient VARCHAR(120) NOT NULL,
    message VARCHAR(255) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    resolved_at VARCHAR(32),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_crossborder_notification_notification_key
    ON crossborder_notification (notification_key);
CREATE INDEX IF NOT EXISTS ix_crossborder_notification_event_key
    ON crossborder_notification (event_key);
CREATE INDEX IF NOT EXISTS ix_crossborder_notification_target_country
    ON crossborder_notification (target_country);
CREATE INDEX IF NOT EXISTS ix_crossborder_notification_status
    ON crossborder_notification (status);
CREATE INDEX IF NOT EXISTS idx_xborder_notif_event_target_status
    ON crossborder_notification (event_key, target_country, status);
