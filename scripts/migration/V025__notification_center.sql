-- V025: Notification centre + audible-alert preferences (EM-086, Epic E8)
-- Tables: notification_states, notification_sound_settings.
--
-- EM-032 already pushes a single ``alert`` onto the live change feed whenever
-- an incident's risk band escalates, but the raw feed is not a *notification
-- centre*: the operator cannot see which alerts they have already handled, a
-- critical warning scrolls away, and the audible alarm is all-or-nothing.
--
-- ``notification_states`` keeps one mutable row per live-feed alert (keyed by
-- live_update_id) carrying the read / acknowledge state. The alert content
-- itself stays in ``live_updates``. ``notification_sound_settings`` keeps a
-- single operator-wide row for the audible alarm (on/off plus the minimum risk
-- band that should sound). Purely additive.

CREATE TABLE IF NOT EXISTS notification_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    live_update_id INTEGER NOT NULL UNIQUE,
    is_read INTEGER NOT NULL DEFAULT 0,
    is_acknowledged INTEGER NOT NULL DEFAULT 0,
    read_at DATETIME,
    acknowledged_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_notification_states_live_update_id
    ON notification_states (live_update_id);

CREATE TABLE IF NOT EXISTS notification_sound_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key VARCHAR(32) NOT NULL UNIQUE,
    sound_enabled INTEGER NOT NULL DEFAULT 1,
    min_level VARCHAR(32) NOT NULL DEFAULT 'dikkat',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_notification_sound_settings_setting_key
    ON notification_sound_settings (setting_key);
