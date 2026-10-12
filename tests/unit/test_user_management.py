"""EM-101 user & role management tests.

Covers the managed service surface (add / edit / activate-deactivate), the role
assignment + country scope (the new ``users.country`` column), the audit-trail
writes to the EM-096 unified ledger (every operation records actor + an old ->
new snapshot), the config catalogue, and the HTTP endpoints both with EM-099
enforcement off (backward-compatible declared actor) and on (401 without a
session, 403 for a role lacking ``manage_users``, allowed for a coordinator).
Also asserts the operator-map wiring.
"""

import pytest
from fastapi.testclient import TestClient

from src.fastapi_app import create_fastapi_app
from src.services.auth import AuthError, create_user, login
from src.services.audit_trail import AUDIT_DOMAINS, list_audit
from src.services.user_management import (
    AUDIT_DOMAIN,
    USER_MGMT_PERSISTENCE,
    USER_NOT_FOUND,
    UserManagementError,
    add_managed_user,
    edit_managed_user,
    list_managed_users,
    set_user_active,
    user_management_config,
)


class _Settings:
    """Deterministic EM-098/099/101 knobs (fast hashing, cheap audit limits)."""

    AUTH_PBKDF2_ITERATIONS = 1000
    AUTH_SESSION_TTL_MINUTES = 240
    AUTH_IDLE_TIMEOUT_MINUTES = 30
    AUTH_MAX_FAILED_LOGINS = 3
    AUTH_LOCKOUT_MINUTES = 10
    AUTH_MIN_PASSWORD_LENGTH = 8
    AUTH_DEMO_BOOTSTRAP_EMAIL = "demo.operator@embermind.test"
    AUTH_DEMO_BOOTSTRAP_PASSWORD = "test-demo-password"
    AUTHZ_ENFORCEMENT_ENABLED = False
    USER_MANAGEMENT_DEFAULT_COUNTRY = ""
    AUDIT_DEFAULT_LIMIT = 50
    AUDIT_MAX_LIMIT = 500


class _DefaultCountrySettings(_Settings):
    """Same, but provisions a TR scope when none is passed explicitly."""

    USER_MANAGEMENT_DEFAULT_COUNTRY = "TR"


# ------------------------------------------------------- service: add ----


def test_add_managed_user_creates_and_audits(session):
    settings = _Settings()
    result = add_managed_user(
        session,
        settings,
        actor="admin@example.test",
        email="new.op@example.test",
        password="sup3rsecret",
        display_name="New Op",
        role="operator",
        country="TR",
    )
    assert result["status"] == "created"
    assert result["user"]["country"] == "TR"
    assert result["user"]["email"] == "new.op@example.test"
    audit = result["audit"]
    assert audit["domain"] == AUDIT_DOMAIN
    assert audit["action"] == "create"
    assert audit["actor"] == "admin@example.test"
    assert audit["new_value"]["role"] == "operator"
    # The write landed in the unified EM-096 ledger, not just the return value.
    trail = list_audit(session, settings, domain=AUDIT_DOMAIN)
    assert trail["total_matching"] >= 1


def test_add_reuses_em098_validation_duplicate(session):
    settings = _Settings()
    add_managed_user(
        session,
        settings,
        actor="a@b.test",
        email="dup@example.test",
        password="sup3rsecret",
        display_name="One",
    )
    with pytest.raises(AuthError):
        add_managed_user(
            session,
            settings,
            actor="a@b.test",
            email="dup@example.test",
            password="sup3rsecret",
            display_name="Two",
        )


def test_add_rejects_bad_country(session):
    settings = _Settings()
    with pytest.raises(UserManagementError):
        add_managed_user(
            session,
            settings,
            actor="a@b.test",
            email="ok@example.test",
            password="sup3rsecret",
            display_name="Ok",
            country="XX",
        )


def test_add_applies_default_country(session):
    settings = _DefaultCountrySettings()
    result = add_managed_user(
        session,
        settings,
        actor="a@b.test",
        email="scoped@example.test",
        password="sup3rsecret",
        display_name="Scoped",
    )
    assert result["user"]["country"] == "TR"


def test_add_global_when_no_country(session):
    settings = _Settings()
    result = add_managed_user(
        session,
        settings,
        actor="a@b.test",
        email="global@example.test",
        password="sup3rsecret",
        display_name="Global",
    )
    assert result["user"]["country"] is None


# ------------------------------------------------------ service: edit ----


def _mk(session, email="edit.me@example.test", role="operator", country="TR"):
    """Create one managed account and return its add-result (for edit tests)."""
    return add_managed_user(
        session,
        _Settings(),
        actor="a@b.test",
        email=email,
        password="sup3rsecret",
        display_name="Edit Me",
        role=role,
        country=country,
    )


def test_edit_role_and_country_audits_delta(session):
    result = _mk(session)
    uid = result["user"]["id"]
    edited = edit_managed_user(
        session,
        _Settings(),
        actor="boss@example.test",
        user_id=uid,
        changes={"role": "coordinator", "country": "GR"},
    )
    assert edited["changed"] is True
    assert set(edited["fields"]) == {"country", "role"}
    assert edited["user"]["role"] == "coordinator"
    assert edited["user"]["country"] == "GR"
    audit = edited["audit"]
    assert audit["action"] == "update"
    assert audit["old_value"]["role"] == "operator"
    assert audit["new_value"]["role"] == "coordinator"
    assert audit["actor"] == "boss@example.test"


def test_edit_clears_country_to_global(session):
    result = _mk(session)
    uid = result["user"]["id"]
    edited = edit_managed_user(
        session,
        _Settings(),
        actor="a@b.test",
        user_id=uid,
        changes={"country": ""},
    )
    assert edited["user"]["country"] is None
    assert "country" in edited["fields"]


def test_edit_noop_when_unchanged(session):
    result = _mk(session)
    uid = result["user"]["id"]
    edited = edit_managed_user(
        session,
        _Settings(),
        actor="a@b.test",
        user_id=uid,
        changes={"role": "operator"},
    )
    assert edited["changed"] is False
    assert edited["audit"] is None


def test_edit_unknown_user(session):
    with pytest.raises(UserManagementError) as exc:
        edit_managed_user(
            session,
            _Settings(),
            actor="a@b.test",
            user_id=999999,
            changes={"role": "admin"},
        )
    assert str(exc.value) == USER_NOT_FOUND


def test_edit_rejects_bad_role(session):
    result = _mk(session)
    with pytest.raises(UserManagementError):
        edit_managed_user(
            session,
            _Settings(),
            actor="a@b.test",
            user_id=result["user"]["id"],
            changes={"role": "wizard"},
        )


def test_edit_rejects_bad_country(session):
    result = _mk(session)
    with pytest.raises(UserManagementError):
        edit_managed_user(
            session,
            _Settings(),
            actor="a@b.test",
            user_id=result["user"]["id"],
            changes={"country": "ZZ"},
        )


# --------------------------------------------------- service: deactivate ----


def test_deactivate_and_activate_audit(session):
    result = _mk(session)
    uid = result["user"]["id"]
    off = set_user_active(
        session, _Settings(), actor="a@b.test", user_id=uid, is_active=False
    )
    assert off["user"]["is_active"] is False
    assert off["audit"]["action"] == "disable"
    on = set_user_active(
        session, _Settings(), actor="a@b.test", user_id=uid, is_active=True
    )
    assert on["user"]["is_active"] is True
    assert on["audit"]["action"] == "enable"
    # Already-active -> no-op, no new audit row.
    noop = set_user_active(
        session, _Settings(), actor="a@b.test", user_id=uid, is_active=True
    )
    assert noop["changed"] is False
    assert noop["audit"] is None


# ------------------------------------------------------- service: list ----


def test_list_and_country_filter(session):
    add_managed_user(
        session,
        _Settings(),
        actor="a@b.test",
        email="tr1@example.test",
        password="sup3rsecret",
        display_name="TR One",
        country="TR",
    )
    add_managed_user(
        session,
        _Settings(),
        actor="a@b.test",
        email="gr1@example.test",
        password="sup3rsecret",
        display_name="GR One",
        country="GR",
    )
    allp = list_managed_users(session, _Settings())
    assert allp["count"] >= 2
    tr = list_managed_users(session, _Settings(), country="TR")
    assert all(u["country"] == "TR" for u in tr["users"])
    assert tr["count"] >= 1


# ------------------------------------------------------- service: config ----


def test_config_catalogue():
    cfg = user_management_config(_Settings())
    assert "operator" in cfg["roles"]
    assert set(cfg["countries"]) == {"TR", "GR"}
    assert cfg["audit_domain"] == AUDIT_DOMAIN
    assert cfg["persistence"] == USER_MGMT_PERSISTENCE
    assert set(cfg["audited_actions"]) == {"create", "update", "enable", "disable"}


def test_audit_domain_registered_in_ledger():
    # EM-101 must reuse the EM-096 controlled vocabulary, having extended it.
    assert "user_management" in AUDIT_DOMAINS


# ----------------------------------------------------------- HTTP ----


def test_route_list_and_add_disabled(client: TestClient):
    resp = client.get("/api/v1/users/manage")
    assert resp.status_code == 200
    assert "users" in resp.json()
    created = client.post(
        "/api/v1/users/manage",
        json={
            "email": "http.op@example.test",
            "password": "sup3rsecret",
            "display_name": "HTTP Op",
            "role": "operator",
            "country": "TR",
            "actor": "seed-admin",
        },
    )
    assert created.status_code == 200
    assert created.json()["user"]["country"] == "TR"
    lst = client.get("/api/v1/users/manage").json()
    assert any(u["email"] == "http.op@example.test" for u in lst["users"])


def test_route_config(client: TestClient):
    resp = client.get("/api/v1/users/manage/config")
    assert resp.status_code == 200
    assert resp.json()["audit_domain"] == AUDIT_DOMAIN


def test_route_edit_and_active(client: TestClient):
    created = client.post(
        "/api/v1/users/manage",
        json={
            "email": "http.edit@example.test",
            "password": "sup3rsecret",
            "display_name": "Edit Target",
            "role": "operator",
        },
    ).json()
    uid = created["user"]["id"]
    patched = client.patch(
        f"/api/v1/users/manage/{uid}",
        json={"role": "coordinator", "country": "GR", "actor": "boss"},
    )
    assert patched.status_code == 200
    assert patched.json()["user"]["role"] == "coordinator"
    deactivated = client.post(
        f"/api/v1/users/manage/{uid}/active",
        json={"is_active": False, "actor": "boss"},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["user"]["is_active"] is False


def test_route_edit_unknown_returns_404(client: TestClient):
    resp = client.patch(
        "/api/v1/users/manage/987654",
        json={"role": "operator", "actor": "boss"},
    )
    assert resp.status_code == 404


def test_route_add_bad_country_returns_400(client: TestClient):
    resp = client.post(
        "/api/v1/users/manage",
        json={
            "email": "bad.country@example.test",
            "password": "sup3rsecret",
            "display_name": "Bad",
            "country": "NOPE",
        },
    )
    assert resp.status_code == 400


def _enforced_client():
    """A testing app with EM-099 enforcement switched ON (isolated in-memory)."""
    app = create_fastapi_app("testing")
    app.state.database.create_all()
    app.state.settings.AUTHZ_ENFORCEMENT_ENABLED = True
    return TestClient(app)


def _make_and_login(client, email, role):
    client.post(
        "/api/v1/auth/users",
        json={
            "email": email,
            "password": "sup3rsecret",
            "display_name": f"{role} {email}",
            "role": role,
        },
    )
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": "sup3rsecret"}
    ).json()["token"]


def test_route_enforced_requires_session():
    with _enforced_client() as c:
        resp = c.post(
            "/api/v1/users/manage",
            json={
                "email": "x@y.test",
                "password": "sup3rsecret",
                "display_name": "X",
            },
        )
        assert resp.status_code == 401


def test_route_enforced_operator_forbidden():
    with _enforced_client() as c:
        tok = _make_and_login(c, "op.noperm@example.test", "operator")
        resp = c.post(
            "/api/v1/users/manage",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "email": "new@y.test",
                "password": "sup3rsecret",
                "display_name": "New",
            },
        )
        # operator has no manage_users permission -> 403.
        assert resp.status_code == 403


def test_route_enforced_coordinator_allowed():
    with _enforced_client() as c:
        tok = _make_and_login(c, "coord.ok@example.test", "coordinator")
        resp = c.post(
            "/api/v1/users/manage",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "email": "provisioned@example.test",
                "password": "sup3rsecret",
                "display_name": "Provisioned",
                "role": "operator",
                "country": "TR",
            },
        )
        assert resp.status_code == 200
        # The audit actor comes from the *proven* session, not a declared label.
        assert resp.json()["audit"]["actor"] == "coord.ok@example.test"
        assert resp.json()["user"]["email"] == "provisioned@example.test"


def test_route_enforced_actor_is_proven_email():
    with _enforced_client() as c:
        tok = _make_and_login(c, "coord.actor@example.test", "coordinator")
        resp = c.post(
            "/api/v1/users/manage",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "email": "target@example.test",
                "password": "sup3rsecret",
                "display_name": "Target",
                # a spoofed declared actor must be ignored when enforced
                "actor": "attacker",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["audit"]["actor"] == "coord.actor@example.test"


# --------------------------------------------------------------- UI ----


def test_ui_wires_user_management_panel():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    for needle in (
        "/api/v1/users/manage",
        "toggleUserMgmtPanel",
        "loadUserMgmt",
        "renderUserMgmt",
        "user-mgmt-open",
    ):
        assert needle in html


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
