"""Shared source loader for operator_map UI-wiring tests.

Code-quality audit: the operator_map page's JavaScript was moved out of the
inline ``<script>`` block into ordered classic scripts (the monolith split).
The markup and its scripts are still one logical unit -- a wiring assertion
about a panel loader, an ``/api`` URL or an innerHTML template should not care
which file the code lives in. This helper bundles them so the existing
behaviour-wiring tests keep passing after the split, with unchanged assertions.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "static"

# Loaded in document order, exactly as the browser executes them.
OPERATOR_MAP_SCRIPTS = (
    "operator_map_core.js",
    "operator_map_panels_a.js",
    "operator_map_panels_b.js",
    "operator_map_init.js",
)


def operator_map_bundle() -> str:
    """Return operator_map.html concatenated with every script it links."""
    parts = [(STATIC_DIR / "operator_map.html").read_text(encoding="utf-8")]
    parts.extend(
        (STATIC_DIR / name).read_text(encoding="utf-8") for name in OPERATOR_MAP_SCRIPTS
    )
    return "\n".join(parts)
