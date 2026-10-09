"""Identity + session endpoints (EM-098, Epic E10).

Email/password login, an authenticated "who am I" read, immediate logout and
the session-policy config. Rejections map onto uniform HTTP statuses so the
UI can say *why* the operator was signed out (bad credentials vs expired vs
locked) without ever revealing whether an e-mail exists.
"""
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from src.database import Database
from src.services.auth import (
    UNIFORM_ACCOUNT_LOCKED,
    UNIFORM_BAD_CREDENTIALS,
    AuthError,
    auth_config,
    bootstrap_demo_user,
    create_user,
    current_user,
    list_users,
    login,
    parse_bearer,
    revoke_session,
)


class LoginRequest(BaseModel):
    """Email + password credentials for one login attempt."""

    email: str
    password: str


class CreateUserRequest(BaseModel):
    """Provision a new account (validated service-side)."""

    email: str
    password: str
    display_name: str
    role: str = "operator"


# Every rejection that means "you are not (or no longer) authenticated".
_UNAUTHENTICATED = {
    UNIFORM_BAD_CREDENTIALS,
    "authentication required",
    "invalid session",
    "session expired",
    "session idle-expired",
    "account inactive",
}


def _http_error(exc: AuthError) -> HTTPException:
    """Map a service error to the right HTTP status (never leaking detail)."""
    text = str(exc)
    if text == UNIFORM_ACCOUNT_LOCKED:
        status = 423  # Locked
    elif text in _UNAUTHENTICATED:
        status = 401  # Unauthorized
    else:
        status = 400  # Validation (duplicate e-mail, weak password, bad role)
    return HTTPException(status_code=status, detail={"status": "error", "error": text})


def register_auth_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the EM-098 auth endpoints."""

    @api.get("/api/v1/auth/config", tags=["panel"])
    def auth_config_endpoint() -> dict[str, Any]:
        """Session policy, roles, hashing + lockout knobs (no secrets)."""
        return auth_config(settings)

    @api.post("/api/v1/auth/login", tags=["panel"])
    def auth_login(req: LoginRequest) -> dict[str, Any]:
        """Authenticate and mint one bearer session.

        A rejected attempt still commits the failed-login counter / lockout so
        brute-force protection survives across requests (the session context
        would otherwise roll the flush back when the error is raised).
        """
        with database.session() as session:
            try:
                result = login(session, settings, req.email, req.password)
            except AuthError as exc:
                session.commit()
                raise _http_error(exc) from exc
            session.commit()
        return result

    @api.get("/api/v1/auth/me", tags=["panel"])
    def auth_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """Resolve the bearer token to its user (TTL + idle timeout enforced)."""
        try:
            with database.session() as session:
                return current_user(session, settings, parse_bearer(authorization))
        except AuthError as exc:
            raise _http_error(exc) from exc

    @api.post("/api/v1/auth/logout", tags=["panel"])
    def auth_logout(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """Revoke the presented session immediately (idempotent)."""
        try:
            with database.session() as session:
                result = revoke_session(session, parse_bearer(authorization))
                session.commit()
        except AuthError as exc:
            raise _http_error(exc) from exc
        return result

    @api.get("/api/v1/auth/users", tags=["auth"])
    def auth_users() -> dict[str, Any]:
        """Account summaries (EM-101 will turn this into an admin surface)."""
        with database.session() as session:
            items = list_users(session)
        return {"count": len(items), "users": items}

    @api.post("/api/v1/auth/users", tags=["auth"])
    def auth_create_user(req: CreateUserRequest) -> dict[str, Any]:
        """Provision a new account (duplicate e-mail / weak password refused)."""
        try:
            with database.session() as session:
                row = create_user(
                    session,
                    settings,
                    email=req.email,
                    password=req.password,
                    display_name=req.display_name,
                    role=req.role,
                )
                session.commit()
                payload = row.as_dict
        except AuthError as exc:
            raise _http_error(exc) from exc
        return {"status": "created", "user": payload}

    @api.post("/api/v1/auth/bootstrap-demo", tags=["auth"])
    def auth_bootstrap_demo() -> dict[str, Any]:
        """Create the labelled demo operator only if no account exists."""
        try:
            with database.session() as session:
                row = bootstrap_demo_user(session, settings)
                session.commit()
        except AuthError as exc:
            raise _http_error(exc) from exc
        if row is None:
            return {"status": "skipped", "reason": "accounts already exist"}
        return {"status": "bootstrapped", "email": row.email}
