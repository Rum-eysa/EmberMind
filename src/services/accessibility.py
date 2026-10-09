"""Operator-surface accessibility contract (EM-085, Epic E8).

Long shifts demand an interface that stays legible for colour-blind operators,
supports a night-shift dark theme and can be driven from the keyboard without a
mouse. The dark theme and the raw colour tokens already ship with the EM-075
design system (``tokens.css``) and the operator choice persists via EM-088; what
was missing is the *contract* that makes those guarantees testable and shared by
every operator surface. This service is that single, deterministic source of
truth:

* a **non-colour-redundant encoding** for every FWI risk level - colour never
  carries information alone; each level also has a Turkish text label, a unique
  glyph and a hatch-pattern id, so an operator who cannot separate the fills
  still reads the state (EM-085 acceptance: "no information depends on colour
  only");
* the recommended **Okabe-Ito colour-blind-safe qualitative palette**, offered
  for any categorical styling and validated for deuteranopia / protanopia /
  tritanopia;
* the **global keyboard-shortcut registry** the operator map binds at document
  level (theme toggle, panel cycling, search focus, help, dismiss) so the whole
  console is usable without a mouse.

Nothing is persisted (``persistence: none``): every value is derived from
settings plus ``RISK_COLORS`` in :mod:`src.services.fwi`, so the accessibility
contract can never drift from the colours actually painted on the map.
"""

from typing import Any

from src.services.fwi import RISK_COLORS

ACCESSIBILITY_PERSISTENCE = "none"
ACCESSIBILITY_ATTRIBUTION = (
    "EM-085: renk körü güvenli palet + renkten-bağımsız risk kodlaması ve genel "
    "klavye kısayolları operatör arayüzüne tek katalogdan sunulur"
)

# Turkish label + distinct glyph + hatch pattern id per FWI risk level. The
# colour is imported from RISK_COLORS (never restated here) so the non-colour
# layer is purely additive: shape and text stay unique under every colour-blind
# simulation, and the key order matches the ordinal FWI ramp low -> extreme.
_RISK_ENCODINGS: dict[str, dict[str, str]] = {
    "very_low": {"label": "Çok Düşük", "glyph": "□", "pattern": "hatch-none"},
    "low": {"label": "Düşük", "glyph": "◇", "pattern": "hatch-dots"},
    "moderate": {"label": "Orta", "glyph": "○", "pattern": "hatch-light"},
    "high": {"label": "Yüksek", "glyph": "△", "pattern": "hatch-medium"},
    "very_high": {"label": "Çok Yüksek", "glyph": "▽", "pattern": "hatch-dense"},
    "extreme": {"label": "Aşırı", "glyph": "✕", "pattern": "hatch-cross"},
}

# Okabe-Ito: a qualitative palette validated for deuteranopia, protanopia and
# tritanopia. Recommended for any categorical (non-ordinal) styling the operator
# adds, complementing the ordinal FWI ramp above.
COLORBLIND_SAFE_PALETTE: dict[str, str] = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "bluish_green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "reddish_purple": "#CC79A7",
}
COLORBLIND_SCHEMES: tuple[str, ...] = ("deuteranopia", "protanopia", "tritanopia")

DEFAULT_THEME = "dark"  # night-shift default; EM-088 persists the operator choice
THEMES: tuple[str, ...] = ("light", "dark", "auto")

# Global keyboard shortcuts the operator map binds on the document. Each is
# deliberately Alt/Shift-modified (except the two guarded singletons) so it never
# collides with typing into an input; ``action`` is the stable handler id the UI
# dispatches on, never the raw label.
DEFAULT_SHORTCUTS: tuple[dict[str, str], ...] = (
    {
        "combo": "Alt+T",
        "action": "toggle_theme",
        "target": "documentElement",
        "description": "Açık/koyu tema arasında geçiş (gece vardiyası)",
    },
    {
        "combo": "Alt+P",
        "action": "cycle_panel",
        "target": "panel",
        "description": "Panel düğmeleri arasında sırayla gezin (klavye ile erişim)",
    },
    {
        "combo": "Alt+K",
        "action": "focus_search",
        "target": "search",
        "description": "Harita aramasına odaklan",
    },
    {
        "combo": "Alt+H",
        "action": "toggle_help",
        "target": "accessibility",
        "description": "Klavye kısayolları yardımını aç/kapat",
    },
    {
        "combo": "Esc",
        "action": "dismiss",
        "target": "overlay",
        "description": "Açık katmanı/paneli kapat",
    },
)


def _theme(settings: Any) -> str:
    """Configured default theme, validated against ``THEMES`` (falls back dark)."""
    value = str(getattr(settings, "ACCESSIBILITY_DEFAULT_THEME", "") or "").strip()
    value = value.lower()
    return value if value in THEMES else DEFAULT_THEME


def _reduced_motion(settings: Any) -> bool:
    """Whether the surface should honour a reduced-motion preference."""
    return bool(getattr(settings, "ACCESSIBILITY_REDUCED_MOTION", False))


def risk_encodings() -> list[dict[str, str]]:
    """Per-level non-colour encoding; the colour mirrors ``RISK_COLORS`` exactly.

    Returns one row per FWI risk level carrying ``color`` (imported, never
    restated), ``label`` (Turkish text), ``glyph`` (unique shape) and ``pattern``
    (hatch id) so information is redundant across at least three channels.
    """
    rows: list[dict[str, str]] = []
    for level, extra in _RISK_ENCODINGS.items():
        rows.append({"level": level, "color": RISK_COLORS[level], **extra})
    return rows


def keyboard_shortcuts() -> list[dict[str, str]]:
    """The global shortcut registry the operator map binds at document level."""
    return [dict(entry) for entry in DEFAULT_SHORTCUTS]


def palette_contract() -> dict[str, Any]:
    """Colour-blind-safety guarantees for the risk ramp + categorical palette."""
    glyphs = [row["glyph"] for row in risk_encodings()]
    patterns = [row["pattern"] for row in risk_encodings()]
    return {
        "risk_levels": len(_RISK_ENCODINGS),
        "color_only_information": False,
        "distinct_glyphs": len(set(glyphs)) == len(glyphs),
        "distinct_patterns": len(set(patterns)) == len(patterns),
        "recommended_qualitative_palette": dict(COLORBLIND_SAFE_PALETTE),
        "validated_for": list(COLORBLIND_SCHEMES),
        "ordinal_ramp_source": "RISK_COLORS (src.services.fwi)",
    }


def accessibility_config(settings: Any = None) -> dict[str, Any]:
    """Full accessibility contract the operator surfaces consume once on load."""
    theme = _theme(settings) if settings is not None else DEFAULT_THEME
    reduced = _reduced_motion(settings) if settings is not None else False
    return {
        "catalog": "accessibility",
        "panel": "accessibility",
        "persistence": ACCESSIBILITY_PERSISTENCE,
        "theme": {
            "default": theme,
            "options": list(THEMES),
            "night_shift_ready": True,
            "persisted_by": "EM-088",
        },
        "reduced_motion": reduced,
        "color_only_information": False,
        "risk_encodings": risk_encodings(),
        "palette": palette_contract(),
        "keyboard_shortcuts": keyboard_shortcuts(),
        "editable_settings": [
            "ACCESSIBILITY_DEFAULT_THEME",
            "ACCESSIBILITY_REDUCED_MOTION",
        ],
        "attribution": ACCESSIBILITY_ATTRIBUTION,
    }


__all__ = [
    "ACCESSIBILITY_ATTRIBUTION",
    "ACCESSIBILITY_PERSISTENCE",
    "COLORBLIND_SAFE_PALETTE",
    "COLORBLIND_SCHEMES",
    "DEFAULT_SHORTCUTS",
    "DEFAULT_THEME",
    "THEMES",
    "accessibility_config",
    "keyboard_shortcuts",
    "palette_contract",
    "risk_encodings",
]
