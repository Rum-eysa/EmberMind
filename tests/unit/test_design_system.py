"""EM-075 design system tests (token sync, component library, theme support)."""
import re
from pathlib import Path

from src.services.fwi import RISK_COLORS

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "static"
TOKENS_CSS = (STATIC_DIR / "tokens.css").read_text(encoding="utf-8")
COMPONENTS_CSS = (STATIC_DIR / "components.css").read_text(encoding="utf-8")
STYLEGUIDE_HTML = (STATIC_DIR / "styleguide.html").read_text(encoding="utf-8")
OPERATOR_MAP_HTML = (STATIC_DIR / "operator_map.html").read_text(encoding="utf-8")
RISK_PANEL_HTML = (STATIC_DIR / "risk_panel.html").read_text(encoding="utf-8")
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")


def _risk_tokens(css: str) -> dict[str, str]:
    """Extract the --risk-* custom properties from the light :root block."""
    root_block = css.split("html[data-theme", 1)[0]
    return {
        match.group(1).replace("-", "_"): match.group(2)
        for match in re.finditer(r"--risk-([a-z-]+):\s*(#[0-9a-f]{6});", root_block)
    }


def test_risk_color_tokens_match_fwi_service_palette():
    """Acceptance: risk threshold colours are the single shared source."""
    assert _risk_tokens(TOKENS_CSS) == RISK_COLORS


def test_tokens_define_colour_typography_and_spacing_scales():
    for token in (
        "--color-primary",
        "--bg-page",
        "--text-primary",
        "--font-family-base",
        "--font-size-xs",
        "--font-size-2xl",
        "--space-1",
        "--space-7",
        "--radius-md",
    ):
        assert token in TOKENS_CSS, token


def test_light_and_dark_themes_are_defined():
    assert ":root {" in TOKENS_CSS
    assert 'html[data-theme="dark"]' in TOKENS_CSS
    assert "@media (prefers-color-scheme: dark)" in TOKENS_CSS
    # Dark theme redefines the surface palette but never the risk colours.
    dark_block = TOKENS_CSS.split('html[data-theme="dark"]', 1)[1].split("}", 1)[0]
    assert "--bg-page" in dark_block
    assert "--risk-" not in dark_block


def test_component_library_covers_required_components():
    for selector in (
        ".em-btn",
        ".em-card",
        ".em-panel",
        ".em-badge",
        ".em-table",
        ".em-form",
        ".em-input",
        ".em-select",
    ):
        assert selector in COMPONENTS_CSS, selector
    # One risk badge variant per FWI category.
    for category in RISK_COLORS:
        assert f".em-badge--risk-{category}" in COMPONENTS_CSS, category


def test_components_use_only_tokens_for_colour_and_spacing():
    """No hard-coded palette hexes inside components.css (tokens own colour)."""
    hexes = re.findall(r"#[0-9a-fA-F]{3,6}", COMPONENTS_CSS)
    assert set(hexes) <= {"#fff", "#222"}, hexes


def test_shared_responsive_and_focus_layer_exists():
    """Code-quality audit: the shared layer stops wide tables overflowing the
    page on narrow screens and gives every control a keyboard focus ring —
    both must be token-based (no hard-coded colour) and live in the two files
    every page already links."""
    # Focus ring is a token, referenced by the universal fallback rule.
    assert "--focus-ring:" in TOKENS_CSS
    assert re.search(r":where\([^)]*\):focus-visible", COMPONENTS_CSS)
    assert "var(--focus-ring)" in COMPONENTS_CSS
    # Tables scroll inside their own box at a small breakpoint, and no new
    # hard-coded hex palette was introduced by the layer.
    assert re.search(r"@media \(max-width: 640px\)\s*\{\s*table", COMPONENTS_CSS)
    assert "overflow-x: auto" in COMPONENTS_CSS


def test_shared_escape_html_helper_is_the_single_source():
    """Code-quality audit A-5: the duplicated XSS guard is collapsed into one
    shared helper (app.js). Each page keeps its own contract by delegating with
    explicit options, so behaviour is preserved byte-for-byte:
    operator_map = String(value) + apostrophe escaping, risk_panel = null->""
    and no apostrophe escaping. The per-page replace chains must be gone."""
    assert "WFS.escapeHtml = function" in APP_JS
    assert "&#" in APP_JS  # escapes entities
    # Both pages load the shared script before their inline script and delegate.
    for page in (OPERATOR_MAP_HTML, RISK_PANEL_HTML):
        assert '<script src="/static/app.js"></script>' in page
        assert "WFS.escapeHtml(value," in page
    # Each page's option reproduces its previous contract, nothing else.
    assert "WFS.escapeHtml(value, { escapeApostrophe: true })" in OPERATOR_MAP_HTML
    assert "WFS.escapeHtml(value, { nullToEmpty: true })" in RISK_PANEL_HTML
    # The old inline replace chains were removed from both pages.
    assert '.replace(/\'/g, "&#39;")' not in OPERATOR_MAP_HTML
    assert 'String(value == null ? "" : value)' not in RISK_PANEL_HTML


def test_styleguide_showcases_all_required_components():
    for fragment in (
        "/static/tokens.css",
        "/static/components.css",
        "em-btn",
        "em-card",
        "em-panel",
        "em-badge",
        "em-table",
        "em-form",
        "theme-toggle",
    ):
        assert fragment in STYLEGUIDE_HTML, fragment


def test_existing_ui_pages_are_wired_to_the_design_system():
    for page in (OPERATOR_MAP_HTML, RISK_PANEL_HTML):
        assert "/static/tokens.css" in page
        assert "/static/components.css" in page
    assert 'data-theme="dark"' in RISK_PANEL_HTML  # commander default theme
    assert "theme-toggle" in RISK_PANEL_HTML


def test_styleguide_endpoint(client):
    response = client.get("/styleguide")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Tasarım Sistemi" in response.text


def test_static_css_endpoints_and_whitelist(client):
    for asset in ("tokens.css", "components.css"):
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/css")
    # No arbitrary file reads through the static route.
    assert client.get("/static/operator_map.html").status_code == 404
    assert client.get("/static/../fastapi_app.py").status_code in (404, 400)


def test_shared_js_asset_is_served(client):
    """Audit A-5: the shared helper must be servable as JavaScript, and the
    static whitelist must still reject anything not explicitly listed."""
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "WFS.escapeHtml" in response.text
    assert client.get("/static/app.html").status_code == 404
