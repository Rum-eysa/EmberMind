"""Email/password identity + server-managed sessions (EM-098, Epic E10).

Until now the system had *no* login at all: every panel and audit row trusts a
free-text ``updated_by`` label, and the only access control is the EM-092 API
key — which authorizes an external *integration*, not a *person*. EM-098 adds
the person layer (acceptance: "e-mail/password login; session duration and
logout management"):

* accounts store a salted PBKDF2-HMAC-SHA256 digest (never the password) and
  a role from the EM-099 vocabulary — enforcement itself is EM-099's job;
* a successful login mints an opaque ``secrets`` bearer token; only its
  SHA-256 fingerprint is persisted, so a stolen database cannot be replayed;
* a session dies three ways: the absolute TTL, the idle timeout (advanced on
  every authenticated read) or an explicit logout that revokes it now;
* brute-force lockout after N failed attempts and *uniform* rejections (the
  response never reveals whether the e-mail exists).

The demo/bootstrap account is created only when the user table is empty and
its password comes from settings — nothing is faked: with zero accounts the
login endpoint honestly rejects every attempt. Persistence: ``users`` +
``user_sessions`` (V034).
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.auth import DEFAULT_ROLE, ROLES, User, UserSession
from src.utils.timeutils import to_utc_iso, utc_now

AUTH_ATTRIBUTION = (
    "EM-098: e-posta/parola girisi, mutlak + hareketsizlik (idle) oturum suresi "
    "ve cikista aninda revocation; brute-force kilitleme ve birlesik reddi "
    "mesajlari"
)
AUTH_PERSISTENCE = "users + user_sessions"

# Demo bootstrap defaults (settings may override; the raw values are demo-only).
DEFAULT_DEMO_EMAIL = "demo.operator@embermind.local"
DEFAULT_DEMO_PASSWORD = "embermind-demo"  # nosec B105 - demo bootstrap default

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Bearer prefix every authenticated endpoint expects in ``Authorization``.
BEARER_PREFIX = "Bearer "

# Generic, enumeration-safe rejection copy (service raises Turkish sentences;
# the route maps them onto these uniform HTTP-level labels).
UNIFORM_BAD_CREDENTIALS = "invalid credentials"
UNIFORM_ACCOUNT_LOCKED = "account temporarily locked"


class AuthError(Exception):
    """Raised for any rejected credential or session operation."""


# ------------------------------------------------------------- password ----
def _hash_password(password: str, iterations: int, salt: Optional[bytes] = None) -> str:
    """Salted PBKDF2-HMAC-SHA256 digest as ``iterations$salt_hex$hash_hex``."""
    raw_salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), raw_salt, iterations
    )
    return f"{iterations}${raw_salt.hex()}${digest.hex()}"


def hash_password(password: str, settings: Any) -> str:
    """Hash with the configured iteration count."""
    return _hash_password(password, pbkdf2_iterations(settings))


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification against a stored digest (never raises)."""
    try:
        iter_text, salt_hex, hash_hex = stored.split("$")
        iterations = int(iter_text)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations
    )
    return hmac.compare_digest(digest, expected)


# ---------------------------------------------------------------- knobs ----
def pbkdf2_iterations(settings: Any) -> int:
    """PBKDF2 round count (floored at 1000 so a typo cannot store MD5-grade)."""
    raw = getattr(settings, "AUTH_PBKDF2_ITERATIONS", 100_000)
    try:
        iterations = int(raw)
    except (TypeError, ValueError):
        return 100_000
    return max(1000, iterations)


def session_ttl_minutes(settings: Any) -> int:
    """Absolute session lifetime, independent of activity (floored at 1)."""
    raw = getattr(settings, "AUTH_SESSION_TTL_MINUTES", 240)
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return 240
    return max(1, minutes)


def idle_timeout_minutes(settings: Any) -> int:
    """Inactivity window after which a session stops authenticating."""
    raw = getattr(settings, "AUTH_IDLE_TIMEOUT_MINUTES", 30)
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return 30
    return max(1, minutes)


def max_failed_logins(settings: Any) -> int:
    """Failed attempts before the account is temporarily locked."""
    raw = getattr(settings, "AUTH_MAX_FAILED_LOGINS", 5)
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return 5
    return max(1, count)


def lockout_minutes(settings: Any) -> int:
    """How long an account stays locked after too many failures."""
    raw = getattr(settings, "AUTH_LOCKOUT_MINUTES", 15)
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return 15
    return max(1, minutes)


def minimum_password_length(settings: Any) -> int:
    """Password length floor enforced at account creation (floored at 8)."""
    raw = getattr(settings, "AUTH_MIN_PASSWORD_LENGTH", 12)
    try:
        length = int(raw)
    except (TypeError, ValueError):
        return 12
    return max(8, length)


def demo_credentials(settings: Any) -> tuple[str, str]:
    """Bootstrap e-mail/password from settings (defaults are demo-only)."""
    email = str(getattr(settings, "AUTH_DEMO_BOOTSTRAP_EMAIL", DEFAULT_DEMO_EMAIL))
    password = str(
        getattr(settings, "AUTH_DEMO_BOOTSTRAP_PASSWORD", DEFAULT_DEMO_PASSWORD)
    )
    return normalize_email(email), password


# ------------------------------------------------------------- accounts ----
def normalize_email(email: str) -> str:
    """Trim + lowercase an e-mail; reject anything that is not user@host.tld."""
    text = str(email or "").strip().lower()
    if not EMAIL_PATTERN.match(text):
        raise AuthError("gecersiz e-posta adresi")
    return text


def _find_user(session: Session, email: str) -> Optional[User]:
    return session.scalars(select(User).where(User.email == email)).first()


def user_count(session: Session) -> int:
    """Number of accounts (used by the empty-DB bootstrap guard)."""
    return int(session.scalar(select(func.count(User.id))) or 0)


def create_user(
    session: Session,
    settings: Any,
    *,
    email: str,
    password: str,
    display_name: str,
    role: str = DEFAULT_ROLE,
) -> User:
    """Validate and persist a new account (EM-101 will expose this as UI)."""
    normalized = normalize_email(email)
    if _find_user(session, normalized) is not None:
        raise AuthError("bu e-posta ile zaten bir hesap var")
    if role not in ROLES:
        raise AuthError(f"gecersiz rol: {role} (izin verilenler: {', '.join(ROLES)})")
    name = str(display_name or "").strip()
    if not name:
        raise AuthError("gorunen ad bos olamaz")
    if len(password or "") < minimum_password_length(settings):
        raise AuthError(
            f"parola en az {minimum_password_length(settings)} karakter olmali"
        )
    row = User(
        email=normalized,
        display_name=name,
        password_digest=hash_password(password, settings),
        role=role,
        is_active=True,
        failed_login_count=0,
    )
    session.add(row)
    session.flush()
    return row


def bootstrap_demo_user(session: Session, settings: Any) -> Optional[User]:
    """Provision the labelled demo account only when *no* account exists.

    Idempotent by construction (the guard is the empty table, not a key). The
    password is never logged or returned; the caller only learns whether a row
    was created.
    """
    if user_count(session) > 0:
        return None
    email, password = demo_credentials(settings)
    return create_user(
        session,
        settings,
        email=email,
        password=password,
        display_name="Demo Operator (EM-098)",
        role="operator",
    )


def list_users(session: Session) -> list[dict[str, Any]]:
    """Accounts, newest first (API views — digest never leaves the table)."""
    rows = session.scalars(select(User).order_by(User.id.desc())).all()
    return [row.as_dict for row in rows]


# --------------------------------------------------------------- login -----
def login(session: Session, settings: Any, email: str, password: str) -> dict[str, Any]:
    """Authenticate and mint one bearer session, or reject uniformly.

    Rejections never reveal whether the e-mail exists (enumeration-safe);
    repeated failures against an existing account trip a temporary lockout.
    """
    now = utc_now()
    normalized = str(email or "").strip().lower()
    row = _find_user(session, normalized) if normalized else None
    if row is None:
        # Still burn a hash so a missing account is not *faster* to reject.
        _hash_password(password or "", pbkdf2_iterations(settings))
        raise AuthError(UNIFORM_BAD_CREDENTIALS)
    if row.locked_until is not None and row.locked_until > now:
        raise AuthError(UNIFORM_ACCOUNT_LOCKED)
    if not row.is_active:
        raise AuthError(UNIFORM_BAD_CREDENTIALS)
    if not verify_password(password or "", str(row.password_digest)):
        row.failed_login_count = int(row.failed_login_count or 0) + 1  # type: ignore[assignment]
        limit = max_failed_logins(settings)
        if row.failed_login_count >= limit:
            row.locked_until = now + timedelta(  # type: ignore[assignment]
                minutes=lockout_minutes(settings)
            )
            row.failed_login_count = 0  # type: ignore[assignment]
        session.flush()
        raise AuthError(UNIFORM_BAD_CREDENTIALS)
    row.failed_login_count = 0  # type: ignore[assignment]
    row.locked_until = None  # type: ignore[assignment]
    row.last_login_at = now  # type: ignore[assignment]
    token, token_hash = _mint_token()
    expiry = now + timedelta(minutes=session_ttl_minutes(settings))
    session.add(
        UserSession(
            token_hash=token_hash,
            user_id=int(row.id),  # type: ignore[arg-type]
            expires_at=expiry,
            last_seen_at=now,
        )
    )
    session.flush()
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": to_utc_iso(expiry),
        "user": row.as_dict,
        "attribution": AUTH_ATTRIBUTION,
    }


def _mint_token() -> tuple[str, str]:
    """Opaque random token + its SHA-256 fingerprint (only the latter lands)."""
    token = secrets.token_urlsafe(32)
    return token, _token_fingerprint(token)


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# -------------------------------------------------------------- session ----
def parse_bearer(header_value: Optional[str]) -> Optional[str]:
    """Extract the token from an ``Authorization: Bearer <token>`` value."""
    if not header_value:
        return None
    text = str(header_value).strip()
    if not text.lower().startswith(BEARER_PREFIX.lower()):
        return None
    token = text[len(BEARER_PREFIX) :].strip()
    return token or None


def current_user(
    session: Session, settings: Any, token: Optional[str]
) -> dict[str, Any]:
    """Resolve a bearer token to its user, enforcing TTL + idle timeout.

    A successful read advances ``last_seen_at`` (sliding idle window within the
    absolute TTL). Expired sessions are reported with distinct reasons so the
    UI can say *why* the operator was signed out.
    """
    now = utc_now()
    if not token:
        raise AuthError("authentication required")
    row = session.scalars(
        select(UserSession).where(UserSession.token_hash == _token_fingerprint(token))
    ).first()
    if row is None or row.revoked_at is not None:
        raise AuthError("invalid session")
    if row.expires_at <= now:
        raise AuthError("session expired")
    idle_cutoff = now - timedelta(minutes=idle_timeout_minutes(settings))
    if row.last_seen_at < idle_cutoff:
        raise AuthError("session idle-expired")
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("account inactive")
    row.last_seen_at = now  # type: ignore[assignment]
    session.flush()
    return {
        "user": user.as_dict,
        "session": {
            "expires_at": to_utc_iso(row.expires_at),
            "last_seen_at": to_utc_iso(row.last_seen_at),
            "idle_timeout_minutes": idle_timeout_minutes(settings),
        },
        "attribution": AUTH_ATTRIBUTION,
    }


def revoke_session(session: Session, token: Optional[str]) -> dict[str, Any]:
    """Logout: stamp ``revoked_at`` once (idempotent for the client)."""
    now = utc_now()
    if not token:
        raise AuthError("authentication required")
    row = session.scalars(
        select(UserSession).where(UserSession.token_hash == _token_fingerprint(token))
    ).first()
    if row is None:
        raise AuthError("invalid session")
    was_active = row.revoked_at is None
    if was_active:
        row.revoked_at = now  # type: ignore[assignment]
        session.flush()
    return {
        "status": "logged_out" if was_active else "already_revoked",
        "attribution": AUTH_ATTRIBUTION,
    }


# --------------------------------------------------------------- config ----
def auth_config(settings: Any) -> dict[str, Any]:
    """Descriptive payload: session policy, roles, hashing + lockout knobs."""
    email, _ = demo_credentials(settings)
    return {
        "catalog": "auth",
        "methods": ["email_password"],
        "token_header": "Authorization",
        "token_scheme": "Bearer",
        "roles": list(ROLES),
        "default_role": DEFAULT_ROLE,
        "session": {
            "ttl_minutes": session_ttl_minutes(settings),
            "idle_timeout_minutes": idle_timeout_minutes(settings),
            "logout_revokes_immediately": True,
        },
        "password": {
            "hash": "pbkdf2-hmac-sha256",
            "iterations": pbkdf2_iterations(settings),
            "min_length": minimum_password_length(settings),
        },
        "lockout": {
            "max_failed_logins": max_failed_logins(settings),
            "lockout_minutes": lockout_minutes(settings),
        },
        "demo_bootstrap": {
            "email": email,
            "only_when_no_accounts_exist": True,
            "password_from_settings": True,
        },
        "editable_settings": [
            "AUTH_SESSION_TTL_MINUTES",
            "AUTH_IDLE_TIMEOUT_MINUTES",
            "AUTH_MAX_FAILED_LOGINS",
            "AUTH_LOCKOUT_MINUTES",
            "AUTH_PBKDF2_ITERATIONS",
            "AUTH_MIN_PASSWORD_LENGTH",
            "AUTH_DEMO_BOOTSTRAP_EMAIL",
            "AUTH_DEMO_BOOTSTRAP_PASSWORD",
        ],
        "persistence": AUTH_PERSISTENCE,
        "attribution": AUTH_ATTRIBUTION,
    }


__all__ = [
    "AUTH_ATTRIBUTION",
    "AUTH_PERSISTENCE",
    "AuthError",
    "DEFAULT_DEMO_EMAIL",
    "EMAIL_PATTERN",
    "ROLES",
    "UNIFORM_ACCOUNT_LOCKED",
    "UNIFORM_BAD_CREDENTIALS",
    "auth_config",
    "bootstrap_demo_user",
    "create_user",
    "current_user",
    "demo_credentials",
    "hash_password",
    "list_users",
    "login",
    "max_failed_logins",
    "normalize_email",
    "parse_bearer",
    "pbkdf2_iterations",
    "revoke_session",
    "session_ttl_minutes",
    "idle_timeout_minutes",
    "user_count",
    "verify_password",
]
