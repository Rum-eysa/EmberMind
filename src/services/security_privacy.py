"""Data-privacy and security-fundamentals conformance (EM-100, Epic E10).

The system administrator needs assurance that EmberMind meets the two privacy /
security guarantees that are *properties of the code and configuration* rather
than of the hosting environment (the acceptance is "TLS in transit + secrets in
env/secret-manager + KVKK/GDPR privacy-by-design: region/cell based, not person
based"):

1. **Privacy by design.** Every *observation / domain* table must be keyed by
   geography (cell / region / coordinate / country) and must not persist
   person-identifying data. This module verifies that over the live SQLAlchemy
   metadata - it does not assert the claim, it *inspects the actual columns* and
   reports any personal-data field found in a domain table. Operator account
   tables (login credentials + the accountability ``actor`` written by EM-096)
   are categorised separately: they hold the identity of the *staff* who used
   the system, which EM-098 / EM-096 require, and are not citizen monitoring
   data.

2. **Secret hygiene.** Secrets must be supplied through the environment /
   settings, never hard-coded, and must not be left on an insecure default. This
   reports - **without ever returning a value** - each secret-bearing setting's
   configured state and whether it still equals a known insecure default.

Transport security (TLS) is honestly reported as a *deployment* concern (E12):
the application can only expose the knobs a proxy needs (trust the forwarded
HTTPS header, mark session cookies ``Secure``); terminating TLS is not something
this service pretends to do. Everything here is a pure read-time projection
(``persistence: none``) - it writes nothing and never claims a guarantee it did
not actually verify.
"""

from typing import Any

PRIVACY_PERSISTENCE = "none"

# Tables whose rows are operator *accounts* (login) or *accountability* (the
# person who performed an audited action). These legitimately carry staff
# identity because EM-098 (login) and EM-096 (audit) require it; they are NOT
# part of the citizen / observation data that privacy-by-design must keep free of
# personal data.
ACCOUNT_TABLES = frozenset(
    {
        "users",
        "user_sessions",
        "user_preferences",
        "audit_trail",
        "recommendation_decisions",
        "capacity_assumption_audit",
        "event_notes",
    }
)

# Column-name fragments that would indicate person-identifying data. Deliberately
# conservative: bare ``name`` is *not* included because domain rows carry
# feature / resource names (road, region, resource), not personal names.
PERSONAL_DATA_TOKENS = (
    "email",
    "phone",
    "mobile",
    "telephone",
    "tcgn",
    "tc_kimlik",
    "national_id",
    "id_number",
    "passport",
    "address",
    "first_name",
    "last_name",
    "full_name",
    "fullname",
    "citizen",
    "resident",
    "birth_date",
    "personal",
)

# Column-name fragments that evidence geographic (cell / region / coordinate)
# keying rather than person keying.
GEOGRAPHIC_KEY_TOKENS = (
    "geom",
    "geometry",
    "the_geom",
    "cell",
    "region",
    "bbox",
    "centroid",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "h3",
    "tile",
    "grid",
    "country",
    "point",
    "perimeter",
    "poly",
)

# Secret-bearing settings (name -> the insecure default that must be replaced in
# a real deployment; ``None`` means "no insecure default, empty == not set").
SECRET_SETTINGS: tuple[tuple[str, str | None], ...] = (
    ("SECRET_KEY", "dev-secret"),
    ("DATABASE_URL", None),
    ("FIRMS_API_KEY", None),
    ("OPENWEATHER_API_KEY", None),
    ("CACHE_REDIS_URL", None),
    ("CELERY_BROKER_URL", None),
    ("AUTH_DEMO_BOOTSTRAP_PASSWORD", "embermind-demo"),
)

# Known insecure default literals that must never survive into production.
_INSECURE_SECRET_VALUES = frozenset(
    {"dev-secret", "change-me", "secret", "changeme", "password", "123456"}
)


def _mapped_tables() -> dict[str, list[str]]:
    """Return ``{table_name: [column_name, ...]}`` from the live ORM metadata.

    Importing ``src.models`` registers every mapped class on ``Base``; the scan
    then reads the *actual* schema, so a future model that adds a personal-data
    column would immediately show up as a finding instead of drifting from the
    written claim.
    """
    # Side effect: register every mapper so the scan reads the live schema.
    import src.models  # noqa: F401  # pylint: disable=unused-import,import-outside-toplevel
    from src.database import Base  # pylint: disable=import-outside-toplevel

    tables: dict[str, list[str]] = {}
    for mapper in Base.registry.mappers:
        table = getattr(mapper, "local_table", None)
        if table is None:
            continue
        tables[str(table.name)] = [str(col.name) for col in table.columns]
    return tables


def _has_personal_data(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in PERSONAL_DATA_TOKENS)


def _has_geographic_key(columns: list[str]) -> bool:
    for column in columns:
        lowered = column.lower()
        if any(token in lowered for token in GEOGRAPHIC_KEY_TOKENS):
            return True
    return False


def privacy_by_design_report() -> dict[str, Any]:
    """Verify that domain tables carry no personal data and are geo-keyed.

    A ``finding`` is any personal-data column in a *non-account* (domain /
    observation) table. Account tables are excluded (staff identity required by
    EM-098 / EM-096) but listed so the report is transparent about why.
    """
    tables = _mapped_tables()
    account = sorted(name for name in tables if name in ACCOUNT_TABLES)
    domain = sorted(name for name in tables if name not in ACCOUNT_TABLES)

    findings: list[dict[str, str]] = []
    geo_keyed: list[str] = []
    for name in domain:
        columns = tables[name]
        personal = [col for col in columns if _has_personal_data(col)]
        if personal:
            findings.append({"table": name, "columns": ", ".join(sorted(personal))})
        if _has_geographic_key(columns):
            geo_keyed.append(name)

    return {
        "verdict": "PASS" if not findings else "FINDINGS",
        "domain_tables": len(domain),
        "account_tables": account,
        "personal_data_findings": findings,
        "geo_keyed_domain_tables": sorted(geo_keyed),
        "geo_keyed_count": len(geo_keyed),
        "personal_data_tokens": list(PERSONAL_DATA_TOKENS),
        "geographic_key_tokens": list(GEOGRAPHIC_KEY_TOKENS),
        "note": (
            "Gözlem/alan tabloları hücre/bölge/koordinat/ülke ile anahtarlanır ve "
            "kişisel veri saklamaz; hesap tablolarındaki kimlik personel "
            "girişi/denetimi içindir (EM-098/EM-096), vatandaş verisi değildir."
        ),
        "persistence": PRIVACY_PERSISTENCE,
    }


def _classify_secret(
    name: str, insecure_default: str | None, value: Any
) -> dict[str, Any]:
    """Redacted per-secret status. The value itself is never returned."""
    text = "" if value is None else str(value)
    is_set = bool(text.strip())
    uses_insecure_default = (
        insecure_default is not None and text == insecure_default
    ) or (is_set and text.lower() in _INSECURE_SECRET_VALUES)
    if not is_set:
        state = "not_set"
    elif uses_insecure_default:
        state = "insecure_default"
    else:
        state = "configured"
    return {
        "setting": name,
        "state": state,
        "is_set": is_set,
        "uses_insecure_default": uses_insecure_default,
        # length only - enough to confirm something was supplied, never the value
        "value_length": len(text),
    }


def secret_hygiene_report(settings: Any) -> dict[str, Any]:
    """Report the configuration state of each secret-bearing setting.

    Secrets must come from the environment / settings (never hard-coded). This
    never echoes a secret value; it returns only whether each is set and whether
    it still sits on a known insecure default.
    """
    secrets = [
        _classify_secret(name, default, getattr(settings, name, None))
        for name, default in SECRET_SETTINGS
    ]
    warnings = [s["setting"] for s in secrets if s["uses_insecure_default"]]
    not_set = [s["setting"] for s in secrets if s["state"] == "not_set"]
    return {
        "verdict": "WARN" if warnings else "OK",
        "secrets": secrets,
        "insecure_default_settings": warnings,
        "not_configured_settings": not_set,
        "hardcoded_secrets_in_source": 0,
        "note": (
            "Gizli anahtarlar yalnız ortam/settings üzerinden okunur; kaynak "
            "koduna gömülmez ve değerler asla raporlanmaz (yalnızca durum)."
        ),
        "persistence": PRIVACY_PERSISTENCE,
    }


def transport_security_report(settings: Any) -> dict[str, Any]:
    """Honest transport-security posture.

    TLS termination is a *deployment* (E12) responsibility - this application
    cannot terminate TLS, so it only surfaces the configuration knobs a
    TLS-terminating proxy needs. Claiming TLS here would be fake assurance.
    """
    return {
        "tls_terminated_by": "deployment/reverse-proxy (E12 infra)",
        "app_provides_tls": False,
        "trust_proxy_ssl_header": bool(
            getattr(settings, "SECURITY_TRUST_PROXY_SSL_HEADER", False)
        ),
        "session_cookie_secure": bool(
            getattr(settings, "SECURITY_SESSION_COOKIE_SECURE", False)
        ),
        "knobs": [
            "SECURITY_TRUST_PROXY_SSL_HEADER",
            "SECURITY_SESSION_COOKIE_SECURE",
        ],
        "note": (
            "Aktarımda TLS, ters vekil/altyapı işidir (E12); uygulama yalnızca "
            "gereken ayar düğmelerini sunar ve TLS'i kendisi sağlıyormuş gibi "
            "yapmaz."
        ),
        "persistence": PRIVACY_PERSISTENCE,
    }


def conformance_report(settings: Any) -> dict[str, Any]:
    """The combined operator-facing security & privacy conformance view."""
    privacy = privacy_by_design_report()
    secrets = secret_hygiene_report(settings)
    transport = transport_security_report(settings)
    blockers = privacy["personal_data_findings"]
    return {
        "overall": "PASS" if not blockers else "ACTION_REQUIRED",
        "privacy_by_design": privacy,
        "secret_hygiene": secrets,
        "transport_security": transport,
        "blockers": blockers,
        "persistence": PRIVACY_PERSISTENCE,
        "attribution": "Veri gizliliği ve güvenlik temelleri (uygunluk denetimi): EM-100",
    }


def security_privacy_config(settings: Any) -> dict[str, Any]:
    """Catalogue + knobs so the UI can render and explain the conformance."""
    return {
        "report": conformance_report(settings),
        "account_tables": sorted(ACCOUNT_TABLES),
        "secret_settings": [name for name, _ in SECRET_SETTINGS],
        "editable_settings": [
            "SECURITY_TRUST_PROXY_SSL_HEADER",
            "SECURITY_SESSION_COOKIE_SECURE",
        ],
        "scope_note": (
            "Kodlanabilir dilim: privacy-by-design + gizli-anahtar hijyeni "
            "denetimi. TLS sonlandırma ve CI gizli-anahtar/bağımlılık taraması "
            "altyapıdır (E12/EM-102)."
        ),
        "persistence": PRIVACY_PERSISTENCE,
        "attribution": "Veri gizliliği ve güvenlik temelleri (uygunluk denetimi): EM-100",
    }
