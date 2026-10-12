"""User & role administration surface (EM-101, Epic E10).

EM-098 gave the system an account and EM-099 gave that account a *role*, but
provisioning and changing accounts still had no admin surface: the only way to
create one was the open ``POST /auth/users`` (no proven actor, no audit) and
there was no way to rename, re-role, scope or deactivate an account at all.
EM-101 closes the acceptance list ("Kullanıcı ekleme, düzenleme, devre dışı
bırakma / Rol atama ve ülke bazlı yetki / Tüm işlemler denetim kaydına yazılır"):

* **add / edit / deactivate** an account through a managed surface, not the raw
  creation endpoint;
* **role assignment plus a country scope** - the new ``users.country`` column
  (V035) records *which* country an account acts for (``TR`` / ``GR``); an empty
  scope means a global, unscoped account;
* **every change is written to the EM-096 unified audit ledger** with the proven
  actor (from an authorized session when enforcement is on) and an old -> new
  value snapshot, so "who changed what, when" is answerable for accounts too.

The permission gate is EM-099's ``manage_users`` - an İzleyici (viewer) or a
plain Saha (field) account cannot administer users. Like EM-099 the enforcement
is only active when switched on; otherwise the surface stays backward-compatible
and honestly reports the declared actor. No new table is introduced: accounts
live on ``users`` (V034/V035) and the trail on ``audit_trail`` (V030).
"""
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.auth import DEFAULT_ROLE, ROLES, User
from src.services.audit_trail import record_audit
from src.services.auth import AuthError, create_user
from src.services.crossborder_situation import COUNTRIES, COUNTRY_LABELS

USER_MGMT_ATTRIBUTION = (
    "EM-101: kullanici ve rol yonetimi ekranlari (ekle/duzenle/devre birak, rol "
    "atama + ulke kapsami); her islem EM-096 birlesik denetim defterine yazar"
)
USER_MGMT_PERSISTENCE = "users.country (V035) + audit_trail (V030)"

# The controlled audit domain this surface writes to (added in EM-096 V030).
AUDIT_DOMAIN = "user_management"

# The pilot countries an account may be scoped to. An empty / ``None`` scope is
# a legal "global" account (no country restriction), so no synthetic code is
# needed to represent it.
MANAGED_COUNTRIES = COUNTRIES


class UserManagementError(ValueError):
    """Raised for an unknown account or an invalid management field."""


USER_NOT_FOUND = "kullanici bulunamadi"


def _resolve_country(value: Any) -> Optional[str]:
    """Upper-case + validate a country scope; empty -> ``None`` (global)."""
    text = str(value or "").strip().upper()
    if not text:
        return None
    if text not in MANAGED_COUNTRIES:
        raise UserManagementError(
            f"gecersiz ulke kapsami: {value} (izin verilenler: "
            f"{', '.join(MANAGED_COUNTRIES)})"
        )
    return text


def _default_country(settings: Any) -> Optional[str]:
    """The configured fallback scope applied when none is passed on create."""
    raw = getattr(settings, "USER_MANAGEMENT_DEFAULT_COUNTRY", "")
    return _resolve_country(raw)


def _clean_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise UserManagementError("gorunen ad bos olamaz")
    return text[:120]


def _find_user(session: Session, user_id: int) -> User:
    row = session.get(User, int(user_id))
    if row is None:
        raise UserManagementError(USER_NOT_FOUND)
    return row


def _audit(
    session: Session,
    settings: Any,
    actor: Optional[str],
    action: str,
    user: User,
    *,
    summary: str,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one accountability row for a user-management action."""
    return record_audit(
        session,
        settings,
        AUDIT_DOMAIN,
        action,
        str(actor or "anonymous"),
        {
            "subject_key": f"user:{int(user.id)}",
            "summary": summary,
            "old_value": old_value,
            "new_value": new_value,
        },
    )


def add_managed_user(
    session: Session,
    settings: Any,
    *,
    actor: Optional[str],
    email: str,
    password: str,
    display_name: str,
    role: str = DEFAULT_ROLE,
    country: Any = None,
) -> dict[str, Any]:
    """Provision an account through the managed surface and audit the creation.

    Delegates all credential validation to EM-098's :func:`create_user` (so the
    duplicate-e-mail / weak-password / bad-role rejections stay identical), then
    attaches the country scope (explicit value, else the configured default).
    """
    row = create_user(
        session,
        settings,
        email=email,
        password=password,
        display_name=display_name,
        role=role,
    )
    scope = (
        _resolve_country(country)
        if country not in (None, "")
        else _default_country(settings)
    )
    if scope is not None:
        row.country = scope  # type: ignore[assignment]
        session.flush()
    snapshot = {
        "email": row.email,
        "display_name": row.display_name,
        "role": row.role,
        "country": row.country,
        "is_active": bool(row.is_active),
    }
    audit = _audit(
        session,
        settings,
        actor,
        "create",
        row,
        summary=f"hesap olusturuldu: {row.email}",
        new_value=snapshot,
    )
    return {"status": "created", "user": row.as_dict, "audit": audit}


def edit_managed_user(
    session: Session,
    settings: Any,
    *,
    actor: Optional[str],
    user_id: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Apply the provided field changes to one account and audit the delta.

    ``changes`` may carry any subset of ``display_name`` / ``role`` /
    ``country``; only present keys are touched, and ``country`` of ``""`` clears
    the scope back to global. The audit row records the before -> after snapshot
    of exactly the fields that actually changed.
    """
    row = _find_user(session, user_id)
    old_snapshot: dict[str, Any] = {}
    new_snapshot: dict[str, Any] = {}

    if "display_name" in changes:
        new_name = _clean_name(changes["display_name"])
        if new_name != row.display_name:
            old_snapshot["display_name"] = row.display_name
            new_snapshot["display_name"] = new_name
            row.display_name = new_name  # type: ignore[assignment]
    if "role" in changes:
        role = str(changes["role"] or "").strip().lower()
        if role not in ROLES:
            raise UserManagementError(
                f"gecersiz rol: {changes['role']} (izin verilenler: {', '.join(ROLES)})"
            )
        if role != row.role:
            old_snapshot["role"] = row.role
            new_snapshot["role"] = role
            row.role = role  # type: ignore[assignment]
    if "country" in changes:
        scope = _resolve_country(changes["country"])
        if scope != row.country:
            old_snapshot["country"] = row.country
            new_snapshot["country"] = scope
            row.country = scope  # type: ignore[assignment]

    session.flush()
    changed = bool(new_snapshot)
    audit: Optional[dict[str, Any]] = None
    if changed:
        fields = ", ".join(sorted(new_snapshot))
        audit = _audit(
            session,
            settings,
            actor,
            "update",
            row,
            summary=f"hesap guncellendi: {fields}",
            old_value=old_snapshot,
            new_value=new_snapshot,
        )
    return {
        "status": "updated" if changed else "noop",
        "changed": changed,
        "fields": sorted(new_snapshot),
        "user": row.as_dict,
        "audit": audit,
    }


def set_user_active(
    session: Session,
    settings: Any,
    *,
    actor: Optional[str],
    user_id: int,
    is_active: bool,
) -> dict[str, Any]:
    """Activate / deactivate one account (the EM-098 login honours the flag).

    Deactivating does not delete the row - EM-098's login already refuses an
    inactive account - so the account and its audit history remain intact.
    """
    row = _find_user(session, user_id)
    target = bool(is_active)
    changed = bool(row.is_active) != target
    if changed:
        row.is_active = target  # type: ignore[assignment]
        session.flush()
    audit: Optional[dict[str, Any]] = None
    if changed:
        audit = _audit(
            session,
            settings,
            actor,
            "enable" if target else "disable",
            row,
            summary=("hesap etkinlestirildi" if target else "hesap devre birakildi")
            + f": {row.email}",
            old_value={"is_active": not target},
            new_value={"is_active": target},
        )
    return {
        "status": "updated" if changed else "noop",
        "changed": changed,
        "user": row.as_dict,
        "audit": audit,
    }


def list_managed_users(
    session: Session, settings: Any, *, country: Optional[str] = None
) -> dict[str, Any]:
    """Managed account list (newest first), optionally filtered by country."""
    stmt = select(User).order_by(User.id.desc())
    if country not in (None, ""):
        stmt = stmt.where(User.country == _resolve_country(country))
    rows = session.scalars(stmt).all()
    users = [row.as_dict for row in rows]
    return {
        "count": len(users),
        "active_count": sum(1 for u in users if u["is_active"]),
        "country_filter": _resolve_country(country) if country else None,
        "users": users,
        "attribution": USER_MGMT_ATTRIBUTION,
        "persistence": USER_MGMT_PERSISTENCE,
    }


def user_management_config(settings: Any) -> dict[str, Any]:
    """Static description of the management surface (roles, countries, audit)."""
    return {
        "catalog": "user_management",
        "roles": list(ROLES),
        "default_role": DEFAULT_ROLE,
        "countries": list(MANAGED_COUNTRIES),
        "country_labels": dict(COUNTRY_LABELS),
        "default_country": _default_country(settings),
        "global_scope": "ulke bos birakilirsa hesap global (kapsamsiz) olur",
        "manage_permission": "manage_users (EM-099)",
        "audit_domain": AUDIT_DOMAIN,
        "audited_actions": ["create", "update", "enable", "disable"],
        "notes": [
            "Ekleme EM-098 create_user validasyonlarini yeniden kullanir.",
            "Her islem EM-096 defterine kim/ne zaman/once->sonra ile yazilir.",
            "Yetki uygulama kapaliyken actor serbest metin olarak declaire edilir "
            "(geriye donuk uyum); acikken kanitlanmis oturumdan alinir.",
        ],
        "editable_settings": ["USER_MANAGEMENT_DEFAULT_COUNTRY"],
        "persistence": USER_MGMT_PERSISTENCE,
        "attribution": USER_MGMT_ATTRIBUTION,
    }


__all__ = [
    "AUDIT_DOMAIN",
    "MANAGED_COUNTRIES",
    "USER_MGMT_ATTRIBUTION",
    "USER_MGMT_PERSISTENCE",
    "USER_NOT_FOUND",
    "UserManagementError",
    "add_managed_user",
    "edit_managed_user",
    "list_managed_users",
    "set_user_active",
    "user_management_config",
]
