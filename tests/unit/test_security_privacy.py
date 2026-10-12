"""EM-100 data-privacy and security conformance tests (Epic E10).

The codeable slice of EM-100 is an *honest* conformance check: privacy by design
verified over the live ORM metadata (region / cell keyed, no personal data in
domain tables), secret hygiene reported *without ever echoing a value*, and a
transport-security posture that names TLS as a deployment (E12) concern instead
of faking it. These tests pin the real-schema PASS, prove the scan is genuine by
injecting a synthetic personal-data column and asserting it becomes a finding,
and confirm no secret value can leak into any report.
"""
import json

from src.services import security_privacy
from src.services.security_privacy import (
    ACCOUNT_TABLES,
    GEOGRAPHIC_KEY_TOKENS,
    PERSONAL_DATA_TOKENS,
    SECRET_SETTINGS,
    _classify_secret,
    _has_geographic_key,
    _has_personal_data,
    _mapped_tables,
    conformance_report,
    privacy_by_design_report,
    security_privacy_config,
    secret_hygiene_report,
    transport_security_report,
)


class _Settings:
    """Minimal settings stub; the service reads knobs via ``getattr``."""

    def __init__(self, **overrides: object) -> None:
        for key, value in overrides.items():
            setattr(self, key, value)


# --------------------------------------------------------------------------- #
# Classification helpers (pure predicates)
# --------------------------------------------------------------------------- #
def test_has_personal_data_matches_tokens():
    assert _has_personal_data("citizen_email") is True
    assert _has_personal_data("TCGN") is True
    assert _has_personal_data("home_address") is True
    assert _has_personal_data("phone_number") is True


def test_has_personal_data_ignores_domain_and_bare_name():
    # bare "name" and geographic / resource columns are NOT personal data
    assert _has_personal_data("region_name") is False
    assert _has_personal_data("resource_name") is False
    assert _has_personal_data("latitude") is False
    assert _has_personal_data("geom") is False


def test_has_geographic_key_detects_spatial_columns():
    assert _has_geographic_key(["id", "cell_id"]) is True
    assert _has_geographic_key(["latitude", "longitude"]) is True
    assert _has_geographic_key(["the_geom"]) is True
    assert _has_geographic_key(["id", "value"]) is False


# --------------------------------------------------------------------------- #
# Live-schema privacy scan (the honest PASS)
# --------------------------------------------------------------------------- #
def test_mapped_tables_reads_the_real_schema():
    tables = _mapped_tables()
    assert "users" in tables
    assert "email" in tables["users"]


def test_privacy_by_design_real_schema_passes():
    report = privacy_by_design_report()
    assert report["verdict"] == "PASS"
    assert report["personal_data_findings"] == []
    assert report["domain_tables"] > 0
    assert report["persistence"] == "none"
    # the account tables that legitimately carry staff identity are surfaced
    assert "users" in report["account_tables"]
    assert report["geo_keyed_count"] > 0


def test_privacy_report_is_transparent_about_tokens():
    report = privacy_by_design_report()
    assert report["personal_data_tokens"] == list(PERSONAL_DATA_TOKENS)
    assert report["geographic_key_tokens"] == list(GEOGRAPHIC_KEY_TOKENS)


def test_privacy_scan_flags_injected_personal_column(monkeypatch):
    # Prove the check is genuine: a future domain table with an email column
    # must surface as a finding, not be silently waved through.
    fake = {
        "users": ["id", "email"],
        "weather_data_points": ["id", "cell_id", "temperature"],
        "citizen_registry": ["id", "tcgn", "full_name"],
    }
    monkeypatch.setattr(security_privacy, "_mapped_tables", lambda: fake)
    report = privacy_by_design_report()
    assert report["verdict"] == "FINDINGS"
    flagged = {f["table"] for f in report["personal_data_findings"]}
    assert flagged == {"citizen_registry"}
    # account tables (users) are categorised, not counted as domain findings
    assert "users" in report["account_tables"]
    assert "citizen_registry" not in ACCOUNT_TABLES


# --------------------------------------------------------------------------- #
# Secret hygiene (redacted)
# --------------------------------------------------------------------------- #
def test_classify_secret_not_set():
    info = _classify_secret("X", None, "")
    assert info["state"] == "not_set"
    assert info["is_set"] is False


def test_classify_secret_insecure_default():
    info = _classify_secret("SECRET_KEY", "dev-secret", "dev-secret")
    assert info["state"] == "insecure_default"
    assert info["uses_insecure_default"] is True


def test_classify_secret_configured_never_leaks_value():
    secret_value = "sup3r-s3cret-do-not-echo"
    info = _classify_secret("DATABASE_URL", None, secret_value)
    assert info["state"] == "configured"
    assert info["is_set"] is True
    # only the length is exposed, never the value
    assert info["value_length"] == len(secret_value)
    assert secret_value not in json.dumps(info)


def test_secret_hygiene_real_settings_are_redacted():
    sentinel = "s3cr3t-api-key-XYZ"
    settings = _Settings(
        SECRET_KEY="dev-secret",
        FIRMS_API_KEY=sentinel,
        OPENWEATHER_API_KEY="",
        DATABASE_URL="postgresql://u:p@h/db",
        CACHE_REDIS_URL="redis://localhost:6379/0",
        CELERY_BROKER_URL="redis://localhost:6379/0",
        AUTH_DEMO_BOOTSTRAP_PASSWORD="test-demo-password",
    )
    report = secret_hygiene_report(settings)
    blob = json.dumps(report)
    assert sentinel not in blob
    assert "test-demo-password" not in blob
    assert report["hardcoded_secrets_in_source"] == 0
    assert report["persistence"] == "none"
    # SECRET_KEY still on its insecure default => a WARN, honestly surfaced
    assert report["verdict"] == "WARN"
    assert "SECRET_KEY" in report["insecure_default_settings"]
    # an unset secret is listed, not treated as a leak
    assert "OPENWEATHER_API_KEY" in report["not_configured_settings"]


def test_secret_hygiene_covers_every_declared_secret():
    report = secret_hygiene_report(_Settings())
    listed = {s["setting"] for s in report["secrets"]}
    assert listed == {name for name, _ in SECRET_SETTINGS}


# --------------------------------------------------------------------------- #
# Transport security (honest: TLS is deployment / E12)
# --------------------------------------------------------------------------- #
def test_transport_report_does_not_claim_tls():
    report = transport_security_report(_Settings())
    assert report["app_provides_tls"] is False
    assert "E12" in report["tls_terminated_by"]
    assert report["persistence"] == "none"


def test_transport_report_surfaces_knobs_from_settings():
    settings = _Settings(
        SECURITY_TRUST_PROXY_SSL_HEADER=True,
        SECURITY_SESSION_COOKIE_SECURE=True,
    )
    report = transport_security_report(settings)
    assert report["trust_proxy_ssl_header"] is True
    assert report["session_cookie_secure"] is True
    assert "SECURITY_TRUST_PROXY_SSL_HEADER" in report["knobs"]


# --------------------------------------------------------------------------- #
# Combined conformance + config
# --------------------------------------------------------------------------- #
def test_conformance_report_combines_and_passes():
    report = conformance_report(_Settings())
    assert report["overall"] == "PASS"
    assert report["blockers"] == []
    assert report["privacy_by_design"]["verdict"] == "PASS"
    assert "secret_hygiene" in report
    assert "transport_security" in report
    assert "EM-100" in report["attribution"]
    assert report["persistence"] == "none"


def test_conformance_flags_blockers_on_injected_finding(monkeypatch):
    fake = {"some_domain_table": ["id", "email"]}
    monkeypatch.setattr(security_privacy, "_mapped_tables", lambda: fake)
    report = conformance_report(_Settings())
    assert report["overall"] == "ACTION_REQUIRED"
    assert report["blockers"]


def test_config_shape_and_scope_note():
    config = security_privacy_config(_Settings())
    assert config["report"] == conformance_report(_Settings())
    assert "users" in config["account_tables"]
    assert config["secret_settings"] == [name for name, _ in SECRET_SETTINGS]
    assert "SECURITY_SESSION_COOKIE_SECURE" in config["editable_settings"]
    assert "E12" in config["scope_note"]
    assert config["persistence"] == "none"


# --------------------------------------------------------------------------- #
# HTTP endpoints (read-only)
# --------------------------------------------------------------------------- #
def test_endpoint_conformance(client):
    resp = client.get("/api/v1/security-privacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"] == "PASS"
    assert body["privacy_by_design"]["verdict"] == "PASS"
    assert "EM-100" in body["attribution"]


def test_endpoint_config(client):
    resp = client.get("/api/v1/security-privacy/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "users" in body["account_tables"]
    assert "SECURITY_TRUST_PROXY_SSL_HEADER" in body["editable_settings"]
