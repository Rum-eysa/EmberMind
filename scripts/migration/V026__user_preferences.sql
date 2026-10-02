-- V026: Persisted operator preference profile (EM-088, Epic E8)
-- Table: user_preferences.
--
-- The interface language (EM-068) and the display standardisation knobs
-- (EM-063: time zone, coordinate format) are stateless - the chosen language
-- lives only in the browser's localStorage and the display helper re-derives
-- everything per request, so neither persists a preference. The theme toggle
-- likewise never leaves the local machine, so switching workstation loses the
-- operator's language / unit / theme choices.
--
-- ``user_preferences`` keeps a single operator-wide row (fixed key) carrying
-- the four display knobs the system already honours, so a saved profile
-- survives a reload / different machine and can be reset to the settings
-- default. Purely additive.

CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preference_key VARCHAR(32) NOT NULL UNIQUE,
    language VARCHAR(8) NOT NULL DEFAULT 'tr',
    theme VARCHAR(16) NOT NULL DEFAULT 'dark',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Istanbul',
    coordinate_format VARCHAR(16) NOT NULL DEFAULT 'decimal',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_user_preferences_preference_key
    ON user_preferences (preference_key);
