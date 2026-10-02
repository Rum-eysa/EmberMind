-- V029: Event & alert webhook subscriptions and delivery ledger (EM-094, Epic E9)
-- Tables: webhook_subscriptions, webhook_deliveries.
--
-- An integrator wants events and alerts pushed to a downstream service the
-- moment they happen instead of polling the live feed. EM-094 acceptance is a
-- configurable webhook URL plus event types, a signed request with retry
-- support, and a viewable delivery history.
--
-- ``webhook_subscriptions`` stores one outbound endpoint (url, the live-feed
-- kinds it cares about, an HMAC signing secret, and an enabled flag).
-- ``webhook_deliveries`` is the append-only ledger of every signed attempt for a
-- subscription against one feed event, recording the body, the signature, the
-- outcome, the attempt number and the next-retry timestamp. Purely additive.

CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_key VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    url VARCHAR(300) NOT NULL,
    event_types VARCHAR(200) NOT NULL DEFAULT '',
    secret VARCHAR(128) NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_webhook_subscriptions_subscription_key
    ON webhook_subscriptions (subscription_key);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_key VARCHAR(64) NOT NULL UNIQUE,
    subscription_id INTEGER NOT NULL,
    subscription_key VARCHAR(64) NOT NULL,
    url VARCHAR(300) NOT NULL,
    live_update_id INTEGER,
    event_type VARCHAR(32) NOT NULL,
    event_key VARCHAR(64),
    request_body TEXT NOT NULL DEFAULT '',
    signature VARCHAR(120) NOT NULL DEFAULT '',
    timestamp_header VARCHAR(40) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    http_status INTEGER,
    attempt INTEGER NOT NULL DEFAULT 1,
    next_retry_at VARCHAR(32),
    error VARCHAR(255),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_delivery_key
    ON webhook_deliveries (delivery_key);

CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_subscription_id
    ON webhook_deliveries (subscription_id);

CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_status
    ON webhook_deliveries (status);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_sub_status
    ON webhook_deliveries (subscription_id, status);
