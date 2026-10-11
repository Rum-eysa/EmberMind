"""EM-099 role-based authorization tests.

Covers the pure RBAC layer (permission vocabulary, the role matrix, the action
map, ``is_allowed`` / ``effective_permissions``), the acceptance sentence
"Izleyici oneri kabul edemez" (a viewer holds only ``view``), the decision-layer
:func:`authorize_action` under enforcement-off / no-session / wrong-role /
right-role, the UI-facing :func:`whoami_permissions`, the config + HTTP
endpoints, and the actual route enforcement (401 without a session, 403 for a
viewer) when the switch is flipped on. Also asserts the operator-map wiring.
"""

import pytest
from fastapi.testclient import TestClient

from src.fastapi_app import create_fastapi_app
from src.services.auth import create_user, login
from src.services.authorization import (
    ACTION_PERMISSION,
    ALL_PERMISSIONS,
    PERM_DECIDE,
    PERM_MANAGE_USERS,
    PERM_RELEASE,
    PERM_VIEW,
    ROLE_PERMISSIONS,
    STATUS_ALLOWED,
    STATUS_DISABLED,
    STATUS_FORBIDDEN,
    STATUS_UNAUTHORIZED,
    authorization_config,
    authorize_action,
    effective_permissions,
    enforcement_enabled,
    is_allowed,
    permissions_for_role,
    required_permission,
    whoami_permissions,
)


class _Settings:
    """Deterministic EM-098 + EM-099 knobs (fast hashing, toggleable switch)."""

    AUTH_PBKDF2_ITERATIONS = 1000
    AUTH_SESSION_TTL_MINUTES = 240
    AUTH_IDLE_TIMEOUT_MINUTES = 30
    AUTH_MAX_FAILED_LOGINS = 3
    AUTH_LOCKOUT_MINUTES = 10
    AUTH_MIN_PASSWORD_LENGTH = 8
    AUTH_DEMO_BOOTSTRAP_EMAIL = "demo.operator@embermind.test"
    AUTH_DEMO_BOOTSTRAP_PASSWORD = "test-demo-password"
    AUTHZ_ENFORCEMENT_ENABLED = True


def _token_for(session, role: str, email: str) -> str:
    """Create a user with ``role`` and return a live bearer token for it."""
    create_user(
        session,
        _Settings(),
        email=email,
        password="sup3rsecret",
        display_name=f"{role} user",
        role=role,
    )
    return login(session, _Settings(), email, "sup3rsecret")["token"]


# ------------------------------------------------------- pure matrix ----


def test_acceptance_viewer_cannot_decide():
    # The literal EM-099 acceptance sentence, expressed as data.
    assert is_allowed("viewer", PERM_DECIDE) is False
    assert PERM_DECIDE not in permissions_for_role("viewer")
    # ... while the working roles can.
    for role in ("operator", "coordinator", "admin"):
        assert is_allowed(role, PERM_DECIDE) is True


def test_five_roles_in_vocabulary():
    assert set(ROLE_PERMISSIONS) == {
        "operator",
        "coordinator",
        "field",
        "viewer",
        "admin",
    }


def test_viewer_is_read_only():
    assert permissions_for_role("viewer") == frozenset({PERM_VIEW})


def test_field_can_release_but_not_decide():
    assert is_allowed("field", PERM_RELEASE) is True
    assert is_allowed("field", PERM_DECIDE) is False


def test_admin_holds_every_permission():
    assert permissions_for_role("admin") == frozenset(ALL_PERMISSIONS)


def test_coordinator_manages_users_operator_does_not():
    assert is_allowed("coordinator", PERM_MANAGE_USERS) is True
    assert is_allowed("operator", PERM_MANAGE_USERS) is False


def test_every_role_at_least_views():
    for role in ROLE_PERMISSIONS:
        assert is_allowed(role, PERM_VIEW) is True


def test_unknown_role_has_no_permissions():
    assert permissions_for_role("ghost") == frozenset()
    assert is_allowed("ghost", PERM_VIEW) is False


def test_required_permission_maps_verbs():
    assert required_permission("accept") == PERM_DECIDE
    assert required_permission("edit") == PERM_DECIDE
    assert required_permission("reject") == PERM_DECIDE
    assert required_permission("release") == PERM_RELEASE
    assert required_permission("bogus") is None


def test_effective_permissions_is_sorted_list():
    perms = effective_permissions("coordinator")
    assert perms == sorted(perms)
    assert set(perms) == set(ROLE_PERMISSIONS["coordinator"])


# --------------------------------------------------------- config ----


def test_enforcement_enabled_reflects_settings():
    assert enforcement_enabled(_Settings()) is True

    class Off:
        pass

    assert enforcement_enabled(Off()) is False  # default when unset


def test_authorization_config_shape():
    cfg = authorization_config(_Settings())
    assert cfg["catalog"] == "authorization"
    assert cfg["enforcement_enabled"] is True
    assert cfg["roles"] == sorted(ROLE_PERMISSIONS)
    assert cfg["action_permission_map"] == dict(ACTION_PERMISSION)
    assert cfg["matrix"]["viewer"] == [PERM_VIEW]
    assert cfg["persistence"] == "none"
    assert "AUTHZ_ENFORCEMENT_ENABLED" in cfg["editable_settings"]


# ------------------------------------------------- authorize_action ----


def test_authorize_action_disabled_short_circuits(session):
    # Enforcement off -> no session required -> the legacy path is preserved.

    class Off(_Settings):
        AUTHZ_ENFORCEMENT_ENABLED = False

    decision = authorize_action(session, Off(), None, PERM_DECIDE)
    assert decision["status"] == STATUS_DISABLED
    assert decision["enforced"] is False


def test_authorize_action_requires_session_when_enforced(session):
    decision = authorize_action(session, _Settings(), None, PERM_DECIDE)
    assert decision["status"] == STATUS_UNAUTHORIZED


def test_authorize_action_rejects_invalid_token(session):
    decision = authorize_action(
        session, _Settings(), "Bearer not-a-real-token", PERM_DECIDE
    )
    assert decision["status"] == STATUS_UNAUTHORIZED


def test_authorize_action_forbids_viewer(session):
    token = _token_for(session, "viewer", "v@example.test")
    decision = authorize_action(session, _Settings(), f"Bearer {token}", PERM_DECIDE)
    assert decision["status"] == STATUS_FORBIDDEN
    assert decision["role"] == "viewer"


def test_authorize_action_allows_operator(session):
    token = _token_for(session, "operator", "o@example.test")
    decision = authorize_action(session, _Settings(), f"Bearer {token}", PERM_DECIDE)
    assert decision["status"] == STATUS_ALLOWED
    assert decision["user"]["role"] == "operator"


def test_authorize_action_field_release_allowed(session):
    token = _token_for(session, "field", "f@example.test")
    assert (
        authorize_action(session, _Settings(), f"Bearer {token}", PERM_RELEASE)[
            "status"
        ]
        == STATUS_ALLOWED
    )
    assert (
        authorize_action(session, _Settings(), f"Bearer {token}", PERM_DECIDE)["status"]
        == STATUS_FORBIDDEN
    )


# ---------------------------------------------------- whoami (UI) ----


def test_whoami_without_token_is_base_read_only(session):
    who = whoami_permissions(session, _Settings(), None)
    assert who["authenticated"] is False
    assert who["can_decide"] is False
    assert who["permissions"] == []


def test_whoami_reports_role_even_when_enforcement_off(session):
    token = _token_for(session, "operator", "o2@example.test")

    class Off(_Settings):
        AUTHZ_ENFORCEMENT_ENABLED = False

    who = whoami_permissions(session, Off(), f"Bearer {token}")
    assert who["enforced"] is False
    assert who["authenticated"] is True
    assert who["role"] == "operator"
    assert who["can_decide"] is True


def test_whoami_viewer_cannot_decide(session):
    token = _token_for(session, "viewer", "v2@example.test")
    who = whoami_permissions(session, _Settings(), f"Bearer {token}")
    assert who["role"] == "viewer"
    assert who["can_decide"] is False
    assert who["permissions"] == [PERM_VIEW]


# ------------------------------------------------------- endpoints ----


def test_config_endpoint(client: TestClient):
    resp = client.get("/api/v1/authz/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["catalog"] == "authorization"
    # Default (testing config) keeps enforcement OFF for backward compatibility.
    assert body["enforcement_enabled"] is False
    assert "viewer" in body["matrix"]


def test_permissions_endpoint(client: TestClient):
    resp = client.get("/api/v1/authz/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matrix"]["viewer"] == ["view"]
    assert body["action_permission_map"]["accept"] == "decide"


def test_effective_endpoint_anonymous(client: TestClient):
    resp = client.get("/api/v1/authz/effective")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False


# ------------------------------------------- route enforcement (401/403) ----


def _enforced_client():
    """A testing app with EM-099 enforcement switched ON (isolated in-memory)."""
    app = create_fastapi_app("testing")
    app.state.database.create_all()
    app.state.settings.AUTHZ_ENFORCEMENT_ENABLED = True
    return TestClient(app)


def test_decision_route_rejects_missing_session():
    with _enforced_client() as c:
        resp = c.post(
            "/api/v1/recommendations/decisions",
            json={"resource_key": "r1", "action": "accept"},
        )
        assert resp.status_code == 401


def test_decision_route_forbids_viewer():
    with _enforced_client() as c:
        # Create + log in a viewer through the EM-098 surface.
        create = c.post(
            "/api/v1/auth/users",
            json={
                "email": "web.viewer@example.test",
                "password": "sup3rsecret",
                "display_name": "Web Viewer",
                "role": "viewer",
            },
        )
        assert create.status_code == 200
        tok = c.post(
            "/api/v1/auth/login",
            json={"email": "web.viewer@example.test", "password": "sup3rsecret"},
        ).json()["token"]
        resp = c.post(
            "/api/v1/recommendations/decisions",
            headers={"Authorization": f"Bearer {tok}"},
            json={"resource_key": "r1", "action": "accept"},
        )
        assert resp.status_code == 403


def test_decision_route_allows_operator_past_authorization():
    with _enforced_client() as c:
        c.post(
            "/api/v1/auth/users",
            json={
                "email": "web.op@example.test",
                "password": "sup3rsecret",
                "display_name": "Web Op",
                "role": "operator",
            },
        )
        tok = c.post(
            "/api/v1/auth/login",
            json={"email": "web.op@example.test", "password": "sup3rsecret"},
        ).json()["token"]
        # Unknown resource -> authz passes, service rejects with 400/404 (not
        # 401/403), proving the operator is authorized to attempt a decision.
        resp = c.post(
            "/api/v1/recommendations/decisions",
            headers={"Authorization": f"Bearer {tok}"},
            json={"resource_key": "does-not-exist", "action": "accept"},
        )
        assert resp.status_code not in (401, 403)


def test_legacy_route_still_works_when_enforcement_off(client: TestClient):
    # TestingConfig has enforcement OFF -> the anonymous path is unchanged.
    resp = client.post(
        "/api/v1/recommendations/decisions",
        json={"resource_key": "does-not-exist", "action": "accept"},
    )
    assert resp.status_code not in (401, 403)


# ----------------------------------------------------------- UI ----


def test_ui_wires_authorization_gating():
    from pathlib import Path

    html = Path("src/static/operator_map.html").read_text(encoding="utf-8")
    for needle in (
        "/api/v1/authz/effective",
        "loadAuthorization",
        "authzCannotDecide",
        "applyAuthorization",
        "can_decide",
    ):
        assert needle in html


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
