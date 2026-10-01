"""EM-068 multilingual interface catalogue tests.

The interface text is resolved from an in-code i18n catalogue: TR and EN carry
the full key set, EL covers the core screens and falls back to EN for the rest.
These tests pin the language normalisation, the fallback chain (locale -> EN ->
raw key), placeholder substitution, catalogue completeness/coverage and the two
read-only endpoints.
"""
import pytest

from src.services.i18n import (
    DEFAULT_LANGUAGE,
    FALLBACK_LANGUAGE,
    SUPPORTED_LANGUAGES,
    I18nError,
    config_payload,
    coverage,
    default_language,
    get_messages,
    messages_payload,
    normalize_language,
    translate,
)


class _EnglishDefault:
    I18N_DEFAULT_LANGUAGE = "en"


class _BadDefault:
    I18N_DEFAULT_LANGUAGE = "de"


# --- language normalisation -------------------------------------------------


def test_supported_languages_are_the_pilot_set():
    assert SUPPORTED_LANGUAGES == ("tr", "en", "el")
    assert DEFAULT_LANGUAGE == "tr"
    assert FALLBACK_LANGUAGE == "en"


@pytest.mark.parametrize(
    "raw,expected",
    [("tr", "tr"), ("EN", "en"), ("el-GR", "el"), ("tr_TR", "tr"), ("en-US", "en")],
)
def test_normalize_accepts_regional_tags(raw, expected):
    assert normalize_language(raw) == expected


def test_normalize_blank_uses_default():
    assert normalize_language(None) == DEFAULT_LANGUAGE
    assert normalize_language("   ") == DEFAULT_LANGUAGE


def test_normalize_unknown_raises():
    with pytest.raises(I18nError):
        normalize_language("de")


def test_default_language_reads_settings_with_guard():
    assert default_language(_EnglishDefault()) == "en"
    # An invalid configured default must not crash the feed.
    assert default_language(_BadDefault()) == DEFAULT_LANGUAGE
    assert default_language(None) == DEFAULT_LANGUAGE


# --- translate / fallback chain --------------------------------------------


def test_translate_returns_locale_text():
    assert translate("card.budget", "tr") == "Yeniden Hesaplama Bütçesi"
    assert translate("card.budget", "en") == "Recompute Budget"


def test_el_core_key_is_greek():
    assert translate("app.title", "el").startswith("Πίνακας")


def test_el_missing_key_falls_back_to_english():
    # ``card.budget`` is intentionally not in the EL core catalogue.
    assert translate("card.budget", "el") == "Recompute Budget"


def test_unknown_locale_and_key_degrade_safely():
    # Unknown locale -> no catalogue -> EN bridge -> raw key (never empty).
    assert translate("card.budget", "zz") == "Recompute Budget"
    assert translate("no.such.key", "tr") == "no.such.key"


def test_translate_substitutes_named_placeholders():
    assert translate("meta.last_update", "en", {"time": "10:30"}) == (
        "last updated: 10:30"
    )
    # An unknown placeholder token is left untouched rather than raising.
    assert translate("meta.last_update", "en", {}) == "last updated: {time}"


# --- catalogue completeness / coverage -------------------------------------


def test_tr_and_en_are_complete_and_aligned():
    assert set(get_messages("tr")) == set(get_messages("en"))


def test_every_message_has_a_tr_and_en_value():
    for key in get_messages("tr"):
        assert translate(key, "tr") != key  # a real translation exists
        assert translate(key, "en") != key


def test_get_messages_always_full_for_any_locale():
    merged = get_messages("el")
    assert set(merged) == set(get_messages("tr"))
    # EL-specific core entry present, EN fallback used for a non-core entry.
    assert merged["card.spread"].startswith("Πρόβλεψη")
    assert merged["card.budget"] == "Recompute Budget"


def test_coverage_marks_el_partial():
    cov = coverage()
    total = cov["tr"]["total"]
    assert cov["tr"] == {"native": total, "total": total, "missing": 0}
    assert cov["en"] == {"native": total, "total": total, "missing": 0}
    assert cov["el"]["native"] < total
    assert cov["el"]["missing"] == total - cov["el"]["native"]


# --- payload builders -------------------------------------------------------


def test_messages_payload_defaults_to_configured_locale():
    payload = messages_payload(None, _EnglishDefault())
    assert payload["language"] == "en"
    assert payload["persistence"] == "none"
    assert payload["supported_languages"] == list(SUPPORTED_LANGUAGES)
    assert payload["messages"]  # non-empty catalogue


def test_messages_payload_for_requested_locale():
    payload = messages_payload("el")
    assert payload["language"] == "el"
    assert payload["fallback_language"] == "en"
    assert set(payload["messages"]) == set(get_messages("tr"))


def test_messages_payload_rejects_unknown_locale():
    with pytest.raises(I18nError):
        messages_payload("fr")


def test_config_payload_lists_locales_with_counts():
    config = config_payload()
    codes = [row["code"] for row in config["supported_languages"]]
    assert codes == ["tr", "en", "el"]
    labels = {row["code"]: row["label"] for row in config["supported_languages"]}
    assert labels["el"] == "Ελληνικά"
    tr_row = config["supported_languages"][0]
    assert tr_row["native_keys"] == tr_row["total_keys"]
    assert config["fallback_language"] == "en"
    assert config["persistence"] == "none"


# --- endpoints --------------------------------------------------------------


def test_endpoint_messages_default(client):
    resp = client.get("/api/v1/i18n/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["language"] == DEFAULT_LANGUAGE
    assert body["messages"]["card.capacity"] == "Müdahale Kapasitesi"


def test_endpoint_messages_requested_locale(client):
    resp = client.get("/api/v1/i18n/messages?lang=en")
    body = resp.json()
    assert body["language"] == "en"
    assert body["messages"]["card.capacity"] == "Response Capacity"


def test_endpoint_messages_bad_locale_is_400(client):
    resp = client.get("/api/v1/i18n/messages?lang=de")
    assert resp.status_code == 400
    assert resp.json()["detail"]["status"] == "error"


def test_endpoint_config(client):
    resp = client.get("/api/v1/i18n/config")
    assert resp.status_code == 200
    assert len(resp.json()["supported_languages"]) == 3
