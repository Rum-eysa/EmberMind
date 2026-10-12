"""Role-based authorization endpoints (EM-099, Epic E10).

Exposes the RBAC matrix (config / permissions) and the caller's effective
permissions so the operator map can gate decision buttons client-side, while the
real enforcement lives on the EM-047 decision endpoints (which call
:func:`authorize_action` before applying any write).
"""

from typing import Any

from fastapi import FastAPI, Header

from src.database import Database
from src.services.authorization import (
    ACTION_PERMISSION,
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    authorization_config,
    effective_permissions,
    whoami_permissions,
)


def register_authorization_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-099 authorization endpoints."""

    @api.get("/api/v1/authz/config", tags=["panel"])
    def authz_config() -> dict[str, Any]:
        """Roles, permission matrix, action map + enforcement switch."""
        return authorization_config(settings)

    @api.get("/api/v1/authz/permissions", tags=["panel"])
    def authz_permissions() -> dict[str, Any]:
        """The static role->permission matrix and verb map (no session)."""
        return {
            "roles": sorted(ROLE_PERMISSIONS),
            "permissions": list(ALL_PERMISSIONS),
            "matrix": {
                role: effective_permissions(role) for role in sorted(ROLE_PERMISSIONS)
            },
            "action_permission_map": dict(ACTION_PERMISSION),
        }

    @api.get("/api/v1/authz/effective", tags=["panel"])
    def authz_effective(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """The caller's role + effective permissions (drives the UI gating)."""
        with database.session() as session:
            return whoami_permissions(session, settings, authorization)
