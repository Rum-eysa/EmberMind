-- V034: kimlik dogrulama hesaplari ve oturumlari (EM-098, Epic E10)
-- Tables: users, user_sessions.
-- users stores one account per row: a normalized lowercase email, a display
-- name, a salted PBKDF2-HMAC-SHA256 password digest (iterations$salt_hex$hash_hex),
-- a role from the EM-099 vocabulary, an active flag and login-failure lockout
-- bookkeeping. The raw password is never persisted. user_sessions stores one
-- issued session per row: only the SHA-256 fingerprint of the opaque bearer
-- token (never the token itself), an absolute expiry, the last-seen time behind
-- the idle timeout and a revocation stamp set by logout. Both tables are
-- purely additive.

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(120) NOT NULL,
    password_digest VARCHAR(512) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'operator',
    is_active BOOLEAN NOT NULL DEFAULT 1,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until DATETIME,
    last_login_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    expires_at DATETIME NOT NULL,
    last_seen_at DATETIME NOT NULL,
    revoked_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_user_sessions_token_hash
    ON user_sessions (token_hash);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id
    ON user_sessions (user_id);
