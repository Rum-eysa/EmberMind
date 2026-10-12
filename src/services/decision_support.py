"""Decision-support framing and responsibility boundary (EM-097, Epic E10).

The commander must always see, on the recommendation screen, that EmberMind is a
*decision support* tool and that the final decision belongs to the authorised
operator - and must know which data / model version produced the advice. When
the pilot runs on synthetic (scenario) data, that fact has to be unmissable on
screen, never silently mixed with real observations.

This is a pure read-time projection: it reads configuration and version knobs
from settings and returns the framing plus a scenario-data badge. Nothing is
persisted (``persistence: none``) - it never fakes an operational decision and
never claims that synthetic data is real.
"""

from typing import Any

SUPPORT_PERSISTENCE = "none"

# Responsibility framing kept intentionally explicit and Turkish (operator UI).
DEFAULT_RESPONSIBILITY_TEXT = (
    "Nihai karar yetkili operatöre aittir; EmberMind yalnızca bir karar destek "
    "aracıdır ve önerileri otomatik uygulanmaz."
)
DEFAULT_MODEL_VERSION = "spread-v1+recommend-v1"
DEFAULT_DATA_VERSION = "pilot-synthetic-2026.08"
SCENARIO_BADGE_LABEL = "SENARYO VERİSİ"
DEFAULT_SCENARIO_NOTICE = (
    "Görünen veriler sentetik senaryo üretimidir; gerçek saha gözlemi değildir. "
    "Operasyonel kararlarda doğrudan esas alınmaz."
)
REAL_DATA_NOTICE = "Veri kaynağı gerçek gözlem olarak işaretlidir; sentetik değildir."


def _responsibility_text(settings: Any) -> str:
    value = getattr(settings, "DECISION_SUPPORT_RESPONSIBILITY_TEXT", "") or ""
    text = str(value).strip()
    return text or DEFAULT_RESPONSIBILITY_TEXT


def _model_version(settings: Any) -> str:
    value = getattr(settings, "DECISION_SUPPORT_MODEL_VERSION", "") or ""
    return str(value).strip() or DEFAULT_MODEL_VERSION


def _data_version(settings: Any) -> str:
    value = getattr(settings, "DECISION_SUPPORT_DATA_VERSION", "") or ""
    return str(value).strip() or DEFAULT_DATA_VERSION


def _scenario_data(settings: Any) -> bool:
    """Whether the running system is fed by synthetic (scenario) data.

    The pilot is deliberately built on synthetic sources (EM-104 synthetic
    generator, EM-035 synthetic signal flow); the flag is surfaced from settings
    so a real deployment can switch it off explicitly rather than us guessing.
    """
    return bool(getattr(settings, "DECISION_SUPPORT_SCENARIO_DATA", True))


def support_framing(settings: Any) -> dict[str, Any]:
    """Return the operator-facing decision-support framing.

    ``advisory_only`` is always ``True``: the system never takes the decision.
    ``scenario_data`` drives the on-screen ``SENARYO VERİSİ`` badge and a
    matching notice; when it is ``False`` the badge label is ``None`` so the UI
    hides it.
    """
    scenario = _scenario_data(settings)
    return {
        "advisory_only": True,
        "decision_owner": "yetkili operatör",
        "responsibility_statement": _responsibility_text(settings),
        "model_version": _model_version(settings),
        "data_version": _data_version(settings),
        "scenario_data": scenario,
        "scenario_badge": SCENARIO_BADGE_LABEL if scenario else None,
        "scenario_notice": DEFAULT_SCENARIO_NOTICE if scenario else REAL_DATA_NOTICE,
        "persistence": SUPPORT_PERSISTENCE,
    }


def support_config(settings: Any) -> dict[str, Any]:
    """Defaults + current knobs so the UI can render and explain the framing."""
    return {
        "framing": support_framing(settings),
        "defaults": {
            "responsibility_text": DEFAULT_RESPONSIBILITY_TEXT,
            "model_version": DEFAULT_MODEL_VERSION,
            "data_version": DEFAULT_DATA_VERSION,
            "scenario_data": True,
        },
        "labels": {
            "scenario_badge": SCENARIO_BADGE_LABEL,
            "decision_owner": "yetkili operatör",
        },
        "editable_settings": [
            "DECISION_SUPPORT_RESPONSIBILITY_TEXT",
            "DECISION_SUPPORT_MODEL_VERSION",
            "DECISION_SUPPORT_DATA_VERSION",
            "DECISION_SUPPORT_SCENARIO_DATA",
        ],
        "persistence": SUPPORT_PERSISTENCE,
        "attribution": "Karar destek çerçevesi / sorumluluk sınırı: EM-097",
    }
