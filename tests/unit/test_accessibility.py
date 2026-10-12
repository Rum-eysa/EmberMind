"""EM-085 operator-surface accessibility contract tests.

The accessibility service is the single, deterministic source of truth for three
guarantees the operator console depends on: a **non-colour-redundant** encoding
for every FWI risk level (colour + Turkish label + unique glyph + hatch pattern,
so no information rides on colour alone), an Okabe-Ito **colour-blind-safe**
qualitative palette, and the **global keyboard-shortcut registry** the operator
map binds at document level. Nothing is persisted (``persistence: none``): every
value is derived from settings plus ``RISK_COLORS``, so the contract can never
drift from the colours actually painted on the map. These tests pin the encoding
shape, the colour mirror, the palette guarantees, the shortcut registry, the
config projections (including theme validation) and the HTTP / UI wiring.
"""
from src.services.accessibility import (
    COLORBLIND_SAFE_PALETTE,
    COLORBLIND_SCHEMES,
    DEFAULT_SHORTCUTS,
    DEFAULT_THEME,
    THEMES,
    accessibility_config,
    keyboard_shortcuts,
    palette_contract,
    risk_encodings,
)
from src.services.fwi import RISK_COLORS


class _Settings:
    """Lightweight settings stub for the two EM-085 knobs."""

    ACCESSIBILITY_DEFAULT_THEME = "dark"
    ACCESSIBILITY_REDUCED_MOTION = False


# ------------------------------------------------------- risk encodings ---


def test_risk_encodings_cover_every_level_in_ramp_order():
    rows = risk_encodings()
    assert [row["level"] for row in rows] == list(RISK_COLORS.keys())


def test_risk_encoding_colour_mirrors_risk_colors():
    # The colour channel must be imported, never restated, or the contract drifts.
    for row in risk_encodings():
        assert row["color"] == RISK_COLORS[row["level"]]


def test_each_level_carries_three_non_colour_channels():
    for row in risk_encodings():
        assert row["label"]  # Turkish text
        assert row["glyph"]  # unique shape
        assert row["pattern"]  # hatch id
        assert set(row) == {"level", "color", "label", "glyph", "pattern"}


def test_glyphs_and_patterns_are_all_distinct():
    rows = risk_encodings()
    assert len({row["glyph"] for row in rows}) == len(rows)
    assert len({row["pattern"] for row in rows}) == len(rows)


# ------------------------------------------------------------- shortcuts ---


def test_keyboard_shortcuts_mirror_the_registry():
    assert keyboard_shortcuts() == [dict(e) for e in DEFAULT_SHORTCUTS]


def test_shortcut_registry_has_unique_actions_and_full_fields():
    actions = [s["action"] for s in keyboard_shortcuts()]
    assert len(actions) == len(set(actions))
    for s in keyboard_shortcuts():
        assert set(s) == {"combo", "action", "target", "description"}
        assert s["combo"] and s["action"] and s["description"]


def test_shortcuts_return_copies_not_shared_state():
    first = keyboard_shortcuts()
    first[0]["combo"] = " mutated"
    assert keyboard_shortcuts()[0]["combo"] != " mutated"


# --------------------------------------------------------------- palette ---


def test_palette_contract_reports_non_colour_redundancy():
    p = palette_contract()
    assert p["color_only_information"] is False
    assert p["distinct_glyphs"] is True
    assert p["distinct_patterns"] is True
    assert p["risk_levels"] == len(RISK_COLORS)
    assert p["ordinal_ramp_source"].startswith("RISK_COLORS")


def test_palette_qualitative_is_okabe_ito_and_validated_for_three_schemes():
    p = palette_contract()
    assert p["recommended_qualitative_palette"] == COLORBLIND_SAFE_PALETTE
    assert set(p["validated_for"]) == set(COLORBLIND_SCHEMES)
    assert len(COLORBLIND_SCHEMES) == 3


# ---------------------------------------------------------------- config ---


def test_config_defaults_without_settings():
    cfg = accessibility_config()
    assert cfg["catalog"] == "accessibility"
    assert cfg["panel"] == "accessibility"
    assert cfg["persistence"] == "none"
    assert cfg["theme"]["default"] == DEFAULT_THEME
    assert cfg["theme"]["night_shift_ready"] is True
    assert cfg["theme"]["persisted_by"] == "EM-088"
    assert cfg["color_only_information"] is False
    assert cfg["reduced_motion"] is False
    assert cfg["attribution"]


def test_config_carries_encodings_palette_and_shortcuts():
    cfg = accessibility_config()
    assert [r["level"] for r in cfg["risk_encodings"]] == list(RISK_COLORS.keys())
    assert cfg["palette"]["distinct_glyphs"] is True
    assert len(cfg["keyboard_shortcuts"]) == len(DEFAULT_SHORTCUTS)


def test_config_editable_settings_lists_the_two_knobs():
    cfg = accessibility_config(_Settings())
    assert "ACCESSIBILITY_DEFAULT_THEME" in cfg["editable_settings"]
    assert "ACCESSIBILITY_REDUCED_MOTION" in cfg["editable_settings"]


def test_config_respects_reduced_motion_flag():
    settings = _Settings()
    settings.ACCESSIBILITY_REDUCED_MOTION = True
    assert accessibility_config(settings)["reduced_motion"] is True


def test_config_honours_configured_theme():
    settings = _Settings()
    settings.ACCESSIBILITY_DEFAULT_THEME = "light"
    assert accessibility_config(settings)["theme"]["default"] == "light"


def test_invalid_theme_falls_back_to_dark():
    settings = _Settings()
    settings.ACCESSIBILITY_DEFAULT_THEME = "neon"
    assert accessibility_config(settings)["theme"]["default"] == DEFAULT_THEME


def test_theme_options_expose_light_dark_auto():
    assert list(THEMES) == accessibility_config()["theme"]["options"]


# ------------------------------------------------------------- endpoint ---


def test_endpoint_config(client):
    body = client.get("/api/v1/accessibility/config").json()
    assert body["panel"] == "accessibility"
    assert body["persistence"] == "none"
    assert body["color_only_information"] is False


def test_endpoint_risk_encodings(client):
    body = client.get("/api/v1/accessibility/risk-encodings").json()
    levels = [row["level"] for row in body["encodings"]]
    assert levels == list(RISK_COLORS.keys())
    assert body["palette"]["distinct_patterns"] is True


def test_endpoint_shortcuts(client):
    body = client.get("/api/v1/accessibility/shortcuts").json()
    assert {s["action"] for s in body["shortcuts"]} == {
        "toggle_theme",
        "cycle_panel",
        "focus_search",
        "toggle_help",
        "dismiss",
    }


# ------------------------------------------------------------------- ui ---


def test_ui_wires_accessibility_panel_and_global_shortcuts():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    assert 'id="a11y-open"' in html
    assert 'id="a11y-panel"' in html
    assert "toggleAccessibilityPanel" in html
    assert "loadAccessibility" in html
    assert "renderA11yEncoding" in html
    assert "bindGlobalShortcuts" in html
    assert "/api/v1/accessibility" in html
