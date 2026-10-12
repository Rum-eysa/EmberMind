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

# operator_map.html monolith split (code-quality audit): the page's inline JS was
# relocated verbatim into these ordered classic scripts, loaded in document order.
OPERATOR_SCRIPTS = (
    "operator_map_core.js",
    "operator_map_panels_a.js",
    "operator_map_panels_b.js",
    "operator_map_init.js",
)
OPERATOR_JS = {
    name: (STATIC_DIR / name).read_text(encoding="utf-8") for name in OPERATOR_SCRIPTS
}
# operator_map.html + its scripts are one logical unit (see the monolith split).
OPERATOR_MAP_BUNDLE = "\n".join(
    [OPERATOR_MAP_HTML] + [OPERATOR_JS[name] for name in OPERATOR_SCRIPTS]
)


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
    # operator_map.html links the shared script before its (now external) code;
    # the escapeHtml delegate lives in the split scripts, so assert on the bundle.
    assert '<script src="/static/app.js"></script>' in OPERATOR_MAP_HTML
    assert '<script src="/static/app.js"></script>' in RISK_PANEL_HTML
    assert "WFS.escapeHtml(value," in OPERATOR_MAP_BUNDLE
    assert "WFS.escapeHtml(value," in RISK_PANEL_HTML
    # Each page's option reproduces its previous contract, nothing else.
    assert "WFS.escapeHtml(value, { escapeApostrophe: true })" in OPERATOR_MAP_BUNDLE
    assert "WFS.escapeHtml(value, { nullToEmpty: true })" in RISK_PANEL_HTML
    # The old inline replace chains were removed from both pages.
    assert '.replace(/\'/g, "&#39;")' not in OPERATOR_MAP_BUNDLE
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


def _top_level_declarations(text: str) -> set[str]:
    """Return identifiers declared at the script's top level.

    operator_map scripts use a 2-space base indent, so only lines starting with
    exactly two spaces are top-level; anything deeper is inside a function or an
    object literal and may legitimately repeat across files.
    """
    pattern = r"^  (?:const|let|var|function|class)\s+([A-Za-z0-9_]+)"
    pattern_async = r"^  async\s+function\s+([A-Za-z0-9_]+)"
    names = set(re.findall(pattern, text, re.MULTILINE))
    names |= set(re.findall(pattern_async, text, re.MULTILINE))
    return names


def test_operator_map_monolith_is_split_into_ordered_scripts():
    """Audit A-monolith: operator_map.html must ship as markup only, linking the
    four scripts in order after the shared app.js, with no inline JS left behind.
    Each external script is a separate classic script, so strict mode does NOT
    propagate across them -- every file must open with its own "use strict".
    The launch call (init().catch) must remain the final executable statement."""
    # The big inline block is gone: no async functions or inline JS left in HTML.
    assert "async function" not in OPERATOR_MAP_HTML
    positions = [
        OPERATOR_MAP_HTML.index(f"/static/{name}") for name in OPERATOR_SCRIPTS
    ]
    assert positions == sorted(positions)  # loaded in the split order
    assert OPERATOR_MAP_HTML.index('/static/app.js"') < positions[0]
    # Strict-mode header preserved per file, and the bootstrap stays last.
    for text in OPERATOR_JS.values():
        body = text.splitlines()
        code = next(i for i, ln in enumerate(body) if ln.strip() == '"use strict";')
        assert body[code + 1].strip()  # real code follows the header
    init_body = [ln.strip() for ln in OPERATOR_JS["operator_map_init.js"].splitlines()]
    launch = [i for i, ln in enumerate(init_body) if ln.startswith("init().catch(")]
    assert launch and launch[-1] == max(i for i, ln in enumerate(init_body) if ln)


def test_operator_map_split_has_no_duplicate_top_level_declarations():
    """Behaviour-safety guard: all classic scripts share one global lexical
    scope, so a `const`/`let`/`function` name declared at top level in two split
    files would throw "already declared" and break the page. The contiguous
    split guarantees disjointness -- this test locks that invariant in."""
    seen: dict[str, str] = {}
    for name in OPERATOR_SCRIPTS:
        for decl in _top_level_declarations(OPERATOR_JS[name]):
            assert decl not in seen, f"{decl} declared in {seen.get(decl)} and {name}"
            seen[decl] = name


def test_operator_map_scripts_are_served(client):
    """The split scripts must be whitelisted and served as JavaScript."""
    for name in OPERATOR_SCRIPTS:
        response = client.get(f"/static/{name}")
        assert response.status_code == 200, name
        assert "javascript" in response.headers["content-type"], name
    # The whitelist is still explicit: unlisted files are rejected.
    assert client.get("/static/operator_map_core.html").status_code == 404
