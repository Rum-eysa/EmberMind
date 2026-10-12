"""Authenticated user accounts + sessions (EM-098, Epic E10).

Every surface in the system is currently anonymous: panels, decisions and
audit rows carry a free-text ``updated_by``/``created_by`` label that the
requester simply types in — nobody *proves* who they are. EM-098 closes the
E10 identity gap with a real email/password login plus a server-side session:

* the password is never stored — only a salted PBKDF2-HMAC-SHA256 digest
  (``iterations$salt_hex$hash_hex``), compared in constant time;
* a login mints an opaque ``secrets`` token; only its SHA-256 fingerprint is
  persisted, so a database leak cannot be replayed as a valid session;
* sessions expire two ways (acceptance: "session duration and logout
  management"): an absolute TTL and an idle timeout, both from settings, and
  logout revokes the token immediately.

The ``ROLES`` tuple is the vocabulary EM-099 will enforce; here it is stored
and echoed but not yet used for authorization. A future EM-101 admin screen
will manage accounts; for now the demo seed provisions one clearly-labelled
demo operator so the login flow is real end to end.
"""
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# Role vocabulary (EM-099 acceptance list). Stored with every account.
ROLES = ("operator", "coordinator", "field", "viewer", "admin")
DEFAULT_ROLE = "operator"


class User(BaseModel):
    """One authenticated account (email + PBKDF2 password digest + role)."""

    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(120), nullable=False)
    # Salted PBKDF2-HMAC-SHA256 digest: "iterations$salt_hex$hash_hex".
    password_digest = Column(String(512), nullable=False)
    role = Column(String(32), nullable=False, default=DEFAULT_ROLE)
    # EM-101: the country this account is scoped to (TR / GR); ``None`` means a
    # global (unscoped) account. Stored alongside the role so "rol atama ve ülke
    # bazlı yetki" is one durable, auditable attribute per account.
    country = Column(String(2), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """API view of the account — never includes the digest."""
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "country": self.country,
            "is_active": bool(self.is_active),
            "locked_until": to_utc_iso(self.locked_until)
            if self.locked_until
            else None,
            "last_login_at": to_utc_iso(self.last_login_at)
            if self.last_login_at
            else None,
            "created_at": to_utc_iso(self.created_at),
        }


class UserSession(BaseModel):
    """One issued session — only the token's SHA-256 fingerprint is stored."""

    __tablename__ = "user_sessions"

    # SHA-256 hex of the opaque bearer token (the raw token never lands).
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """API view of the session (no token material at all)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "expires_at": to_utc_iso(self.expires_at),
            "last_seen_at": to_utc_iso(self.last_seen_at),
            "revoked_at": to_utc_iso(self.revoked_at) if self.revoked_at else None,
        }
