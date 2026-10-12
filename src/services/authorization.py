"""Role-based authorization over the EM-098 identity layer (EM-099, Epic E10).

EM-098 gave the system a *person* (an e-mail/password login and a bearer
session) but deliberately stored the role without ever *using* it: every write
endpoint — above all the EM-047 recommendation decision (accept / edit / reject)
— still trusted a free-text ``decided_by`` label anyone could type. EM-099 is the
authorization half the acceptance list demands:

* the five roles are Operatör, Koordinatör, Saha, İzleyici, Yönetici;
* **an İzleyici (viewer) cannot accept a proposal** — nor edit, reject or free a
  committed unit; a viewer is read-only by construction.

Like EM-092 this is a *pure decision layer*: :func:`authorize_action` returns a
status token the route turns into an HTTP outcome (``unauthorized`` -> 401,
``forbidden`` -> 403, ``allowed`` / ``disabled`` -> proceed). Enforcement is only
active when it is switched on; otherwise the surface is honestly reported as
``disabled`` so local development and the whole existing anonymous decision
surface keep working and we never pretend a control is guarding traffic it is not.

Persistence is ``none``: the role already lives on EM-098's ``users`` table
(V034) — nothing new is stored here, only read and checked.
"""

from typing import Any, Optional

from sqlalchemy.orm import Session

from src.services.auth import AuthError, current_user, parse_bearer

AUTHZ_ATTRIBUTION = (
    "EM-099: EM-098 rolleri uzerinde rol tabanli yetkilendirme "
    "(izleyici oneri kabul/ret/duzenleyemez; kararin kim tarafindan verildigi "
    "kanitlanmis oturumdan gelir)"
)
AUTHZ_PERSISTENCE = "none"

# Permission vocabulary. Coarse enough to be auditable, fine enough that a
# viewer is genuinely read-only and a field crew cannot commit command-post
# decisions. ``view`` is the baseline every role holds.
PERM_VIEW = "view"
PERM_DECIDE = "decide"  # accept / edit / reject a positioning proposal
PERM_RELEASE = "release"  # free a committed unit (task completion)
PERM_MANAGE_USERS = "manage_users"  # provision accounts (EM-101 surface)

ALL_PERMISSIONS = (PERM_VIEW, PERM_DECIDE, PERM_RELEASE, PERM_MANAGE_USERS)

# Role -> granted permissions. The role keys are EM-098's ``ROLES`` vocabulary;
# the acceptance sentence "İzleyici öneriyi kabul edemez" is exactly the viewer
# row lacking ``decide`` (and every other write permission).
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "operator": frozenset({PERM_VIEW, PERM_DECIDE, PERM_RELEASE}),
    "coordinator": frozenset({PERM_VIEW, PERM_DECIDE, PERM_RELEASE, PERM_MANAGE_USERS}),
    "field": frozenset({PERM_VIEW, PERM_RELEASE}),
    "viewer": frozenset({PERM_VIEW}),
    "admin": frozenset(ALL_PERMISSIONS),
}

# Map a decision *action* (EM-047 verb) onto the permission it requires, so the
# route asks for a semantic permission rather than hard-coding a role test.
ACTION_PERMISSION: dict[str, str] = {
    "accept": PERM_DECIDE,
    "edit": PERM_DECIDE,
    "reject": PERM_DECIDE,
    "release": PERM_RELEASE,
}

# Human-readable status tokens returned by :func:`authorize_action`; the route
# maps them to HTTP (unauthorized -> 401, forbidden -> 403).
STATUS_ALLOWED = "allowed"
STATUS_UNAUTHORIZED = "unauthorized"
STATUS_FORBIDDEN = "forbidden"
STATUS_DISABLED = "disabled"


def enforcement_enabled(settings: Any) -> bool:
    """Whether role enforcement is switched on (default off -> legacy surface)."""
    return bool(getattr(settings, "AUTHZ_ENFORCEMENT_ENABLED", False))


def required_permission(action: str) -> Optional[str]:
    """The permission an EM-047 action needs, or ``None`` for an unknown verb."""
    return ACTION_PERMISSION.get(str(action or "").strip().lower())


def permissions_for_role(role: str) -> frozenset[str]:
    """The frozen permission set granted to a role (unknown role -> nothing)."""
    return ROLE_PERMISSIONS.get(str(role or "").strip().lower(), frozenset())


def is_allowed(role: str, permission: str) -> bool:
    """Whether a role holds one permission."""
    return permission in permissions_for_role(role)


def effective_permissions(role: str) -> list[str]:
    """A role's permissions as a stable, sorted list (for config + the UI)."""
    return sorted(permissions_for_role(role))


def authorize_action(
    session: Session,
    settings: Any,
    authorization_header: Optional[str],
    permission: str,
) -> dict[str, Any]:
    """Resolve a bearer session and decide whether its role may act.

    The route turns the ``status`` into an HTTP outcome:
    ``unauthorized`` -> 401, ``forbidden`` -> 403, ``allowed`` / ``disabled`` ->
    proceed. When enforcement is off no session is required and the legacy
    free-text path is left untouched (``disabled``).
    """
    if not enforcement_enabled(settings):
        return {"status": STATUS_DISABLED, "enforced": False, "permission": permission}
    token = parse_bearer(authorization_header)
    try:
        resolved = current_user(session, settings, token)
    except AuthError as exc:
        return {
            "status": STATUS_UNAUTHORIZED,
            "enforced": True,
            "permission": permission,
            "reason": str(exc),
        }
    role = str(resolved["user"].get("role", ""))
    if not is_allowed(role, permission):
        return {
            "status": STATUS_FORBIDDEN,
            "enforced": True,
            "permission": permission,
            "role": role,
        }
    return {
        "status": STATUS_ALLOWED,
        "enforced": True,
        "permission": permission,
        "role": role,
        "user": resolved["user"],
    }


def whoami_permissions(
    session: Session,
    settings: Any,
    authorization_header: Optional[str],
) -> dict[str, Any]:
    """Describe the caller's role + effective permissions (drives the UI).

    Unlike :func:`authorize_action` this answers whether a *presented* session
    can decide even when enforcement is off, so the operator map can grey out
    the accept buttons for a viewer without waiting for a rejection round-trip.
    """
    enforced = enforcement_enabled(settings)
    token = parse_bearer(authorization_header)
    base: dict[str, Any] = {
        "enforced": enforced,
        "authenticated": False,
        "role": None,
        "permissions": [],
        "can_decide": False,
        "can_release": False,
    }
    if not token:
        return base
    try:
        resolved = current_user(session, settings, token)
    except AuthError as exc:
        return {**base, "reason": str(exc)}
    role = str(resolved["user"].get("role", ""))
    return {
        "enforced": enforced,
        "authenticated": True,
        "role": role,
        "display_name": resolved["user"].get("display_name"),
        "permissions": effective_permissions(role),
        "can_decide": is_allowed(role, PERM_DECIDE),
        "can_release": is_allowed(role, PERM_RELEASE),
    }


def authorization_config(settings: Any) -> dict[str, Any]:
    """Static description of the RBAC surface: roles, matrix, action map."""
    return {
        "catalog": "authorization",
        "enforcement_enabled": enforcement_enabled(settings),
        "roles": sorted(ROLE_PERMISSIONS),
        "permissions": list(ALL_PERMISSIONS),
        "matrix": {
            role: effective_permissions(role) for role in sorted(ROLE_PERMISSIONS)
        },
        "action_permission_map": dict(ACTION_PERMISSION),
        "role_source": "users.role (EM-098, V034)",
        "notes": [
            "Izleyici yalnizca goruntuleyebilir; oneri kabul/ret/duzenleyemez.",
            "Yetki uygulama kapaliyken yaz uclari serbest metin decided_by ile "
            "geriye donuk uyumlu calisir (EM-092 deseni).",
        ],
        "editable_settings": ["AUTHZ_ENFORCEMENT_ENABLED"],
        "persistence": AUTHZ_PERSISTENCE,
        "attribution": AUTHZ_ATTRIBUTION,
    }


__all__ = [
    "ACTION_PERMISSION",
    "ALL_PERMISSIONS",
    "AUTHZ_ATTRIBUTION",
    "AUTHZ_PERSISTENCE",
    "PERM_DECIDE",
    "PERM_MANAGE_USERS",
    "PERM_RELEASE",
    "PERM_VIEW",
    "ROLE_PERMISSIONS",
    "STATUS_ALLOWED",
    "STATUS_DISABLED",
    "STATUS_FORBIDDEN",
    "STATUS_UNAUTHORIZED",
    "authorization_config",
    "authorize_action",
    "effective_permissions",
    "enforcement_enabled",
    "is_allowed",
    "permissions_for_role",
    "required_permission",
    "whoami_permissions",
]
