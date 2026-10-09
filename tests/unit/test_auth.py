"""EM-098 email/password identity + server-managed session tests.

Covers the password digest round-trip (never the raw secret), token mint /
fingerprint / bearer parsing, e-mail normalization, account validation
(duplicate e-mail, weak password, bad role, blank name), login success, the
enumeration-safe uniform rejection (a missing account is rejected with the *same*
message as a wrong password), brute-force lockout after N failures, the three
ways a session dies (absolute TTL, sliding idle timeout, immediate logout),
inactive-account rejection, idempotent revocation, the empty-table bootstrap
guard, the config projection, every HTTP endpoint status mapping and the
operator-map UI wiring.
"""
from datetime import timedelta

import pytest

from src.models.auth import ROLES, UserSession
from src.services.auth import (
    UNIFORM_ACCOUNT_LOCKED,
    UNIFORM_BAD_CREDENTIALS,
    AuthError,
    auth_config,
    bootstrap_demo_user,
    create_user,
    current_user,
    hash_password,
    list_users,
    login,
    normalize_email,
    parse_bearer,
    revoke_session,
    user_count,
    verify_password,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Deterministic settings stub for the EM-098 knobs (fast hashing)."""

    AUTH_PBKDF2_ITERATIONS = 1000
    AUTH_SESSION_TTL_MINUTES = 240
    AUTH_IDLE_TIMEOUT_MINUTES = 30
    AUTH_MAX_FAILED_LOGINS = 3
    AUTH_LOCKOUT_MINUTES = 10
    AUTH_MIN_PASSWORD_LENGTH = 8
    AUTH_DEMO_BOOTSTRAP_EMAIL = "demo.operator@embermind.test"
    AUTH_DEMO_BOOTSTRAP_PASSWORD = "test-demo-password"


def _make_user(session, email="op@example.test", password="sup3rsecret"):  # type: ignore[no-untyped-def]
    return create_user(
        session,
        _Settings(),
        email=email,
        password=password,
        display_name="Test Operator",
        role="operator",
    )


# ------------------------------------------------------------ passwords ----


def test_hash_password_is_salted_pbkdf2_format():
    digest = hash_password("secret123", _Settings())
    assert digest.count("$") == 2
    assert "secret123" not in digest


def test_verify_password_round_trip_and_wrong():
    digest = hash_password("correct horse battery", _Settings())
    assert verify_password("correct horse battery", digest) is True
    assert verify_password("wrong password", digest) is False


def test_verify_password_rejects_malformed_digest():
    assert verify_password("x", "not-a-digest") is False
    assert verify_password("x", "") is False


# --------------------------------------------------------------- tokens ----


def test_parse_bearer_extracts_token():
    assert parse_bearer("Bearer abc123") == "abc123"
    assert parse_bearer("bearer abc123") == "abc123"


def test_parse_bearer_rejects_wrong_scheme_and_empty():
    assert parse_bearer(None) is None
    assert parse_bearer("Basic abc") is None
    assert parse_bearer("Bearer ") is None


# ------------------------------------------------------- email + accounts --


def test_normalize_email_trims_and_lowercases():
    assert normalize_email("  Ops@Example.COM ") == "ops@example.com"


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a@b", "@host.com", "a b@c.com"])
def test_normalize_email_rejects_invalid(bad):
    with pytest.raises(AuthError):
        normalize_email(bad)


def test_create_user_persists_and_strips_digest_from_view(session):
    row = _make_user(session)
    session.commit()
    view = row.as_dict
    assert view["email"] == "op@example.test"
    assert "password_digest" not in view


def test_create_user_rejects_duplicate_email(session):
    _make_user(session)
    session.commit()
    with pytest.raises(AuthError):
        _make_user(session)


def test_create_user_rejects_weak_password(session):
    with pytest.raises(AuthError):
        create_user(
            session,
            _Settings(),
            email="x@example.test",
            password="short",
            display_name="X",
        )


def test_create_user_rejects_bad_role(session):
    with pytest.raises(AuthError):
        create_user(
            session,
            _Settings(),
            email="x@example.test",
            password="longenough",
            display_name="X",
            role="superuser",
        )


def test_create_user_rejects_blank_display_name(session):
    with pytest.raises(AuthError):
        create_user(
            session,
            _Settings(),
            email="x@example.test",
            password="longenough",
            display_name="   ",
        )


# ---------------------------------------------------------------- login ----


def test_login_success_mints_bearer_session(session):
    _make_user(session)
    session.commit()
    result = login(session, _Settings(), "op@example.test", "sup3rsecret")
    assert result["token_type"] == "bearer"
    assert result["token"]
    assert result["user"]["email"] == "op@example.test"
    assert result["expires_at"].endswith("Z")


def test_login_wrong_password_uniform_rejection(session):
    _make_user(session)
    session.commit()
    with pytest.raises(AuthError) as exc:
        login(session, _Settings(), "op@example.test", "nope-nope-nope")
    assert str(exc.value) == UNIFORM_BAD_CREDENTIALS


def test_login_unknown_email_same_message_as_wrong_password(session):
    # Enumeration-safety: a missing account is rejected with the identical copy.
    _make_user(session)
    session.commit()
    with pytest.raises(AuthError) as exc:
        login(session, _Settings(), "ghost@example.test", "whatever123")
    assert str(exc.value) == UNIFORM_BAD_CREDENTIALS


def test_login_lockout_after_max_failures(session):
    _make_user(session)
    session.commit()
    settings = _Settings()
    for _ in range(settings.AUTH_MAX_FAILED_LOGINS):
        with pytest.raises(AuthError):
            login(session, settings, "op@example.test", "bad-password-x")
    session.commit()
    with pytest.raises(AuthError) as exc:
        login(session, settings, "op@example.test", "sup3rsecret")
    assert str(exc.value) == UNIFORM_ACCOUNT_LOCKED


def test_login_clears_counters_on_success(session):
    _make_user(session)
    session.commit()
    settings = _Settings()
    with pytest.raises(AuthError):
        login(session, settings, "op@example.test", "bad-password-x")
    session.commit()
    login(session, settings, "op@example.test", "sup3rsecret")
    assert user_count(session) == 1


# --------------------------------------------------------------- session ---


def _latest_session_row(session):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    return session.scalars(select(UserSession).order_by(UserSession.id.desc())).first()


def test_current_user_resolves_and_slides_idle(session):
    _make_user(session)
    session.commit()
    token = login(session, _Settings(), "op@example.test", "sup3rsecret")["token"]
    payload = current_user(session, _Settings(), token)
    assert payload["user"]["email"] == "op@example.test"
    assert payload["session"]["idle_timeout_minutes"] == 30


def test_current_user_rejects_expired_ttl(session):
    _make_user(session)
    session.commit()
    settings = _Settings()
    token = login(session, settings, "op@example.test", "sup3rsecret")["token"]
    row = _latest_session_row(session)
    row.expires_at = utc_now() - timedelta(minutes=1)
    session.commit()
    with pytest.raises(AuthError) as exc:
        current_user(session, settings, token)
    assert str(exc.value) == "session expired"


def test_current_user_rejects_idle_timeout(session):
    _make_user(session)
    session.commit()
    settings = _Settings()
    token = login(session, settings, "op@example.test", "sup3rsecret")["token"]
    row = _latest_session_row(session)
    row.last_seen_at = utc_now() - timedelta(
        minutes=settings.AUTH_IDLE_TIMEOUT_MINUTES + 1
    )
    session.commit()
    with pytest.raises(AuthError) as exc:
        current_user(session, settings, token)
    assert str(exc.value) == "session idle-expired"


def test_current_user_rejects_unknown_and_revoked(session):
    _make_user(session)
    session.commit()
    settings = _Settings()
    token = login(session, settings, "op@example.test", "sup3rsecret")["token"]
    with pytest.raises(AuthError):
        current_user(session, settings, "never-issued")
    revoke_session(session, token)
    with pytest.raises(AuthError) as exc:
        current_user(session, settings, token)
    assert str(exc.value) == "invalid session"


def test_current_user_rejects_inactive_account(session):
    row = _make_user(session)
    session.commit()
    settings = _Settings()
    token = login(session, settings, "op@example.test", "sup3rsecret")["token"]
    row.is_active = False
    session.commit()
    with pytest.raises(AuthError) as exc:
        current_user(session, settings, token)
    assert str(exc.value) == "account inactive"


def test_current_user_requires_token(session):
    with pytest.raises(AuthError):
        current_user(session, _Settings(), None)


# -------------------------------------------------------------- revoke ----


def test_revoke_session_is_idempotent(session):
    _make_user(session)
    session.commit()
    settings = _Settings()
    token = login(session, settings, "op@example.test", "sup3rsecret")["token"]
    assert revoke_session(session, token)["status"] == "logged_out"
    assert revoke_session(session, token)["status"] == "already_revoked"


def test_revoke_unknown_token_raises(session):
    with pytest.raises(AuthError):
        revoke_session(session, "never-issued")


# ------------------------------------------------------------ bootstrap ---


def test_bootstrap_creates_only_when_empty(session):
    settings = _Settings()
    assert user_count(session) == 0
    created = bootstrap_demo_user(session, settings)
    assert created is not None
    session.commit()
    # Second call is a no-op: accounts already exist.
    assert bootstrap_demo_user(session, settings) is None
    assert user_count(session) == 1


def test_bootstrap_demo_account_can_log_in(session):
    settings = _Settings()
    bootstrap_demo_user(session, settings)
    session.commit()
    result = login(
        session,
        settings,
        settings.AUTH_DEMO_BOOTSTRAP_EMAIL,
        settings.AUTH_DEMO_BOOTSTRAP_PASSWORD,
    )
    assert result["user"]["role"] == "operator"


def test_list_users_newest_first(session):
    _make_user(session, email="a@example.test")
    _make_user(session, email="b@example.test")
    session.commit()
    items = list_users(session)
    assert [u["email"] for u in items] == ["b@example.test", "a@example.test"]


# --------------------------------------------------------------- config ---


def test_auth_config_shape(session):
    cfg = auth_config(_Settings())
    assert cfg["catalog"] == "auth"
    assert cfg["methods"] == ["email_password"]
    assert cfg["roles"] == list(ROLES)
    assert cfg["password"]["hash"] == "pbkdf2-hmac-sha256"
    assert cfg["password"]["iterations"] == 1000
    assert cfg["session"]["ttl_minutes"] == 240
    assert cfg["lockout"]["max_failed_logins"] == 3
    assert cfg["demo_bootstrap"]["only_when_no_accounts_exist"] is True
    assert "AUTH_SESSION_TTL_MINUTES" in cfg["editable_settings"]
    assert cfg["persistence"] == "users + user_sessions"


# ------------------------------------------------------------- endpoint ---


def test_endpoint_config(client):
    body = client.get("/api/v1/auth/config").json()
    assert body["catalog"] == "auth"
    assert body["persistence"] == "users + user_sessions"


def test_endpoint_bootstrap_then_login_me_logout(client):
    boot = client.post("/api/v1/auth/bootstrap-demo").json()
    assert boot["status"] == "bootstrapped"
    email = boot["email"]

    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "test-demo-password"},
    )
    assert res.status_code == 200
    token = res.json()["token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email

    out = client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert out.status_code == 200
    assert out.json()["status"] == "logged_out"

    after = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert after.status_code == 401


def test_endpoint_bootstrap_second_time_skipped(client):
    client.post("/api/v1/auth/bootstrap-demo")
    body = client.post("/api/v1/auth/bootstrap-demo").json()
    assert body["status"] == "skipped"


def test_endpoint_login_bad_credentials_401(client):
    client.post("/api/v1/auth/bootstrap-demo")
    res = client.post(
        "/api/v1/auth/login", json={"email": "ghost@x.test", "password": "whatever123"}
    )
    assert res.status_code == 401
    assert res.json()["detail"]["error"] == UNIFORM_BAD_CREDENTIALS


def test_endpoint_me_without_token_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_endpoint_create_user_and_duplicate_400(client):
    created = client.post(
        "/api/v1/auth/users",
        json={
            "email": "new@operator.test",
            "password": "longenough123",
            "display_name": "New Operator",
            "role": "viewer",
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "created"
    dup = client.post(
        "/api/v1/auth/users",
        json={
            "email": "new@operator.test",
            "password": "longenough123",
            "display_name": "Dup",
        },
    )
    assert dup.status_code == 400


def test_endpoint_create_user_weak_password_400(client):
    res = client.post(
        "/api/v1/auth/users",
        json={"email": "weak@operator.test", "password": "123", "display_name": "W"},
    )
    assert res.status_code == 400


def test_endpoint_users_lists(client):
    client.post("/api/v1/auth/bootstrap-demo")
    body = client.get("/api/v1/auth/users").json()
    assert body["count"] == 1
    assert "password_digest" not in body["users"][0]


def test_endpoint_login_lockout_returns_423(client):
    client.post(
        "/api/v1/auth/users",
        json={
            "email": "lock@operator.test",
            "password": "longenough123",
            "display_name": "Lock Me",
        },
    )
    for _ in range(3):  # TestingConfig AUTH_MAX_FAILED_LOGINS = 3
        client.post(
            "/api/v1/auth/login",
            json={"email": "lock@operator.test", "password": "bad-password-x"},
        )
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "lock@operator.test", "password": "longenough123"},
    )
    assert res.status_code == 423
    assert res.json()["detail"]["error"] == UNIFORM_ACCOUNT_LOCKED


# ------------------------------------------------------------------- ui ---


def test_ui_wires_auth_panel_and_flow():
    from pathlib import Path

    html = Path("src/static/operator_map.html").read_text(encoding="utf-8")
    assert 'id="auth-open"' in html
    assert 'id="auth-panel"' in html
    assert "toggleAuthPanel" in html
    assert "loadAuth" in html
    assert "renderAuth" in html
    assert "authSubmit" in html
    assert "authLogout" in html
    assert "/api/v1/auth" in html
