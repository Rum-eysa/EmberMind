"""Country / role data-sharing authorization policy tests (EM-070).

The policy is the durable authorization layer EM-066 deferred: an administrator
decides, per owner country and role scope, which field groups (``fire`` /
``risk`` / ``support``) may cross the border to the partner. Resolution walks
explicit-role -> country-default -> configured default, every change appends an
audit row (the newest row per key is the effective policy) and a ``preview``
shows exactly what the partner would see. These tests cover that EM-070
behaviour - resolution precedence, append-only audit, preview and the feed.
"""
import pytest

from src.services.share_policy import (
    DEFAULT_ROLE,
    SharePolicyError,
    audit_trail,
    effective_shared_fields,
    policy_matrix,
    preview_sharing,
    resolve_effective,
    set_policy,
)


class _Settings:
    """Configured fallback shares everything (mirrors the env default)."""

    SHARE_POLICY_DEFAULT_FIELDS = "fire,risk,support"


class _RiskOnlySettings(_Settings):
    """A tighter configured default: only the risk group when nothing is set."""

    SHARE_POLICY_DEFAULT_FIELDS = "risk"


# --------------------------------------------------------------------------
# field normalisation
# --------------------------------------------------------------------------
def test_normalize_accepts_csv_and_sequence_in_canonical_order():
    from src.services.share_policy import _normalize_fields

    assert _normalize_fields("support,fire") == ["fire", "support"]
    assert _normalize_fields(["risk", "fire"]) == ["fire", "risk"]
    assert _normalize_fields(None) == []


def test_normalize_empty_selection_is_legal():
    from src.services.share_policy import _normalize_fields

    assert _normalize_fields("") == []
    assert _normalize_fields([]) == []


def test_normalize_rejects_unknown_field():
    from src.services.share_policy import _normalize_fields

    with pytest.raises(SharePolicyError):
        _normalize_fields(["fire", "personnel"])


# --------------------------------------------------------------------------
# effective resolution + precedence
# --------------------------------------------------------------------------
def test_effective_defaults_to_configured_when_no_rows(session):
    fields = effective_shared_fields(session, _Settings(), "TR")
    assert fields == ["fire", "risk", "support"]
    resolved = resolve_effective(session, _Settings(), "TR", DEFAULT_ROLE)
    assert resolved["source"] == "configured_default"


def test_effective_uses_tighter_configured_default(session):
    fields = effective_shared_fields(session, _RiskOnlySettings(), "GR")
    assert fields == ["risk"]


def test_set_policy_appends_and_updates_effective(session):
    result = set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire", "risk"])
    assert result["changed"] is True
    assert result["shared_fields_after"] == ["fire", "risk"]
    fields = effective_shared_fields(session, _Settings(), "TR")
    assert fields == ["fire", "risk"]


def test_explicit_role_overrides_country_default(session):
    set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire"])
    set_policy(session, _Settings(), "TR", "coordinator", ["fire", "risk", "support"])
    resolved = resolve_effective(session, _Settings(), "TR", "coordinator")
    assert resolved["shared_fields"] == ["fire", "risk", "support"]
    assert resolved["source"] == "role_policy"


def test_named_role_inherits_country_default(session):
    set_policy(session, _Settings(), "GR", DEFAULT_ROLE, ["risk"])
    resolved = resolve_effective(session, _Settings(), "GR", "operator")
    assert resolved["shared_fields"] == ["risk"]
    assert resolved["source"] == "country_default"


def test_share_nothing_selection(session):
    set_policy(session, _Settings(), "TR", DEFAULT_ROLE, [])
    assert effective_shared_fields(session, _Settings(), "TR") == []


def test_unknown_country_raises(session):
    with pytest.raises(SharePolicyError):
        effective_shared_fields(session, _Settings(), "XX")


def test_invalid_field_raises_on_set(session):
    with pytest.raises(SharePolicyError):
        set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["secret"])


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------
def test_preview_lists_shared_and_denied(session):
    set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire"])
    preview = preview_sharing(session, _Settings(), "TR")
    assert preview["shared_fields"] == ["fire"]
    assert preview["denied_fields"] == ["risk", "support"]
    assert "Türkiye" in preview["message"]


# --------------------------------------------------------------------------
# append-only audit trail
# --------------------------------------------------------------------------
def test_audit_records_before_after_chain(session):
    set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire", "risk"])
    set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire"], changed_by="admin")
    rows = audit_trail(session, country="TR")
    assert len(rows) == 2
    newest, older = rows[0], rows[1]
    assert newest["shared_fields"] == ["fire"]
    assert newest["previous_shared_fields"] == ["fire", "risk"]
    assert newest["changed_by"] == "admin"
    assert older["shared_fields"] == ["fire", "risk"]


def test_noop_change_flags_unchanged_but_still_audited(session):
    first = set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire"])
    second = set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire"])
    assert first["changed"] is True
    assert second["changed"] is False
    assert len(audit_trail(session, country="TR")) == 2


def test_audit_trail_filters_by_role(session):
    set_policy(session, _Settings(), "TR", DEFAULT_ROLE, ["fire"])
    set_policy(session, _Settings(), "TR", "operator", ["risk"])
    rows = audit_trail(session, country="TR", role="operator")
    assert len(rows) == 1
    assert rows[0]["role"] == "operator"


# --------------------------------------------------------------------------
# matrix
# --------------------------------------------------------------------------
def test_policy_matrix_lists_both_countries(session):
    matrix = policy_matrix(session, _Settings())
    codes = {entry["country"] for entry in matrix["countries"]}
    assert codes == {"TR", "GR"}
    for entry in matrix["countries"]:
        roles = {role["role"] for role in entry["roles"]}
        assert DEFAULT_ROLE in roles


def test_policy_matrix_flags_explicit_rows(session):
    set_policy(session, _Settings(), "TR", "coordinator", ["fire"])
    matrix = policy_matrix(session, _Settings())
    tr = next(e for e in matrix["countries"] if e["country"] == "TR")
    coord = next(r for r in tr["roles"] if r["role"] == "coordinator")
    assert coord["explicit"] is True
    assert coord["source"] == "role_policy"


# --------------------------------------------------------------------------
# HTTP feed
# --------------------------------------------------------------------------
def test_endpoint_matrix(client):
    resp = client.get("/api/v1/share-policy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persistence"] == "country_share_policy"
    assert len(body["countries"]) == 2


def test_endpoint_preview_default(client):
    resp = client.get("/api/v1/share-policy/preview?country=TR")
    assert resp.status_code == 200
    body = resp.json()
    assert body["viewer_country"] == "TR"
    assert "shared_fields" in body


def test_endpoint_preview_bad_country_400(client):
    resp = client.get("/api/v1/share-policy/preview?country=XX")
    assert resp.status_code == 400


def test_endpoint_set_then_effective_and_audit(client, session):
    resp = client.post(
        "/api/v1/share-policy",
        json={"country": "GR", "shared_fields": ["risk"], "changed_by": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "set"
    fields = effective_shared_fields(session, _Settings(), "GR")
    assert fields == ["risk"]
    audit = client.get("/api/v1/share-policy/audit?country=GR")
    assert audit.status_code == 200
    assert audit.json()["count"] >= 1


def test_endpoint_set_invalid_field_400(client):
    resp = client.post(
        "/api/v1/share-policy",
        json={"country": "TR", "shared_fields": ["nope"]},
    )
    assert resp.status_code == 400
