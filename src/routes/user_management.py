"""User & role administration endpoints (EM-101, Epic E10).

Exposes the managed add / edit / deactivate surface, the account list and the
role + country catalogue. Writes are gated by EM-099's ``manage_users``
permission: when enforcement is on an unauthenticated caller gets 401 and a
role without the permission (e.g. a viewer) gets 403, and the audit actor is
taken from the *proven* session; when enforcement is off the legacy free-text
``actor`` keeps working so nothing is broken.
"""
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.auth import AuthError
from src.services.authorization import (
    PERM_MANAGE_USERS,
    STATUS_FORBIDDEN,
    STATUS_UNAUTHORIZED,
    authorize_action,
)
from src.services.user_management import (
    USER_NOT_FOUND,
    UserManagementError,
    add_managed_user,
    edit_managed_user,
    list_managed_users,
    set_user_active,
    user_management_config,
)


class AddUserRequest(BaseModel):
    """Provision an account through the managed surface."""

    email: str
    password: str
    display_name: str
    role: str = "operator"
    country: Optional[str] = None
    actor: Optional[str] = None


class EditUserRequest(BaseModel):
    """Partial edit: only the fields present in the body are touched."""

    display_name: Optional[str] = None
    role: Optional[str] = None
    country: Optional[str] = None
    actor: Optional[str] = None


class ActiveRequest(BaseModel):
    """Activate / deactivate one account."""

    is_active: bool
    actor: Optional[str] = None


def _http_error(exc: Exception) -> HTTPException:
    """Map a service error to an HTTP status (404 unknown account, else 400)."""
    text = str(exc)
    status = 404 if text == USER_NOT_FOUND else 400
    return HTTPException(status_code=status, detail={"status": "error", "error": text})


def _resolve_actor(
    session: Any, settings: Any, authorization: Optional[str], declared: Optional[str]
) -> str:
    """Gate a write on ``manage_users`` and return the audit actor."""
    decision = authorize_action(session, settings, authorization, PERM_MANAGE_USERS)
    if decision["status"] == STATUS_UNAUTHORIZED:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "error": "authentication required"},
        )
    if decision["status"] == STATUS_FORBIDDEN:
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "error": "role may not manage users"},
        )
    if decision.get("enforced"):
        user = decision.get("user") or {}
        return str(user.get("email") or declared or "anonymous")
    return str(declared or "anonymous")


def register_user_management_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-101 user & role management endpoints."""

    @api.get("/api/v1/users/manage/config", tags=["auth"])
    def users_manage_config() -> dict[str, Any]:
        """Roles, countries + the audit domain the surface writes to."""
        return user_management_config(settings)

    @api.get("/api/v1/users/manage", tags=["auth"])
    def users_manage_list(
        country: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        """Managed account summaries (never the password digest)."""
        with database.session() as session:
            return list_managed_users(session, settings, country=country)

    @api.post("/api/v1/users/manage", tags=["auth"])
    def users_manage_add(
        req: AddUserRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Provision an account (reuses EM-098 validation) + audit the create."""
        with database.session() as session:
            actor = _resolve_actor(session, settings, authorization, req.actor)
            try:
                result = add_managed_user(
                    session,
                    settings,
                    actor=actor,
                    email=req.email,
                    password=req.password,
                    display_name=req.display_name,
                    role=req.role,
                    country=req.country,
                )
                session.commit()
            except (AuthError, UserManagementError) as exc:
                raise _http_error(exc) from exc
        return result

    @api.patch("/api/v1/users/manage/{user_id}", tags=["auth"])
    def users_manage_edit(
        user_id: int,
        req: EditUserRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Edit display_name / role / country (partial) + audit the delta."""
        changes = {
            field: getattr(req, field)
            for field in ("display_name", "role", "country")
            if field in req.model_fields_set
        }
        with database.session() as session:
            actor = _resolve_actor(session, settings, authorization, req.actor)
            try:
                result = edit_managed_user(
                    session,
                    settings,
                    actor=actor,
                    user_id=user_id,
                    changes=changes,
                )
                session.commit()
            except (AuthError, UserManagementError) as exc:
                raise _http_error(exc) from exc
        return result

    @api.post("/api/v1/users/manage/{user_id}/active", tags=["auth"])
    def users_manage_active(
        user_id: int,
        req: ActiveRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Activate / deactivate an account + audit the toggle."""
        with database.session() as session:
            actor = _resolve_actor(session, settings, authorization, req.actor)
            try:
                result = set_user_active(
                    session,
                    settings,
                    actor=actor,
                    user_id=user_id,
                    is_active=req.is_active,
                )
                session.commit()
            except (AuthError, UserManagementError) as exc:
                raise _http_error(exc) from exc
        return result
