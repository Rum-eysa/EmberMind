"""Silent-zone confidence labelling for false-alarm prevention (EM-038, Epic E4).

Not every *silence* is an emergency. EM-035 learns each monitored cell's normal
communication/report level and flags the ones that read unusually quiet today
(``candidate_silent``); EM-038's job is to stop the operator from chasing false
alarms among those candidates. A cell can look "silent" for two very different
reasons (EM-038 acceptance: "sinyali zaten zayıf bölgelerle aniden sessizleşen
bölgeleri ayırt etmek"):

* **structurally weak coverage** - the cell barely reports anything even in its
  own baseline (chronically low ``baseline_mean``) or has too few observations
  to trust. Its quietness is a *measurement artefact*, not a fire signal, so it
  earns a **"düşük güven"** (low-confidence) label and should not page anyone;
* **previously normal, suddenly silent** - the cell had a healthy reporting
  baseline and then dropped sharply below it. That is the genuine emergency
  pattern and earns a **"yüksek güven"** (high-confidence) label.

A cell with sound coverage whose drop is present but not pronounced sits in an
**"orta güven"** band so the operator can triage between the two extremes.

This is a read-time projection: it reuses
:func:`src.services.signal_baseline.baseline_report` verbatim and adds nothing
to storage, so ``persistence`` is ``none``. The synthetic-source caveat carries
through - the whole ladder is computed on the labelled synthetic pilot flow,
never presented as real telemetry.
"""
from typing import Any, Optional

from src.services.signal_baseline import (
    BASELINE_PERSISTENCE,
    baseline_report,
)

DEFAULT_MIN_COVERAGE_SIGNAL = 100.0
DEFAULT_MIN_OBSERVATIONS = 7
DEFAULT_STRONG_DROP_Z = 2.5
DEFAULT_MAX_LIMIT = 200

CONFIDENCE_LABELS: dict[str, str] = {
    "high": "Yüksek güven",
    "medium": "Orta güven",
    "low": "Düşük güven",
}
CONFIDENCE_ORDER: tuple[str, ...] = ("high", "medium", "low")

SILENT_ZONE_CONFIDENCE_ATTRIBUTION = (
    "EM-038: EM-035 hücre baz çizgisi yeniden kullanılarak sessiz adaylar "
    "kapsama gücüne ve ani düşüş derecesine göre düşük/orta/yüksek güven "
    "etiketiyle sınıflanır; yanlış alarm önleme"
)
SILENT_ZONE_CONFIDENCE_PERSISTENCE = BASELINE_PERSISTENCE


class SilentZoneConfidenceError(ValueError):
    """Raised for an invalid caller-supplied filter (mapped to HTTP 400)."""


def _min_coverage_signal(settings: Any) -> float:
    return float(
        getattr(
            settings, "FALSE_ALARM_MIN_COVERAGE_SIGNAL", DEFAULT_MIN_COVERAGE_SIGNAL
        )
    )


def _min_observations(settings: Any) -> int:
    return int(
        getattr(settings, "FALSE_ALARM_MIN_OBSERVATIONS", DEFAULT_MIN_OBSERVATIONS)
    )


def _strong_drop_z(settings: Any) -> float:
    return float(getattr(settings, "FALSE_ALARM_STRONG_DROP_Z", DEFAULT_STRONG_DROP_Z))


def _max_limit(settings: Any) -> int:
    return int(getattr(settings, "FALSE_ALARM_MAX_LIMIT", DEFAULT_MAX_LIMIT))


def _coverage_strength(
    row: dict[str, Any], min_coverage_signal: float, min_observations: int
) -> str:
    """Classify the *structural* reporting presence behind a cell's baseline."""
    if int(row["observation_count"]) < min_observations:
        return "insufficient_data"
    if float(row["baseline_mean"]) < min_coverage_signal:
        return "weak"
    return "sound"


def classify_cell(row: dict[str, Any], settings: Any) -> dict[str, Any]:
    """Attach a false-alarm confidence label to one EM-035 baseline cell row.

    Only ``candidate_silent`` cells receive a confidence tier; a normal (not
    unusually quiet) cell is reported as not-flagged with a ``None`` code so the
    caller still sees why it is absent from the alerting ladder.
    """
    min_coverage_signal = _min_coverage_signal(settings)
    min_observations = _min_observations(settings)
    strong_drop_z = _strong_drop_z(settings)

    coverage_strength = _coverage_strength(row, min_coverage_signal, min_observations)
    sudden_drop = bool(float(row["z_score"]) <= -strong_drop_z)

    reasons: list[str] = []
    code: Optional[str]
    if not row["candidate_silent"]:
        code = None
        reasons.append(
            "Bugünkü okuma baz çizgisine göre anormal derecede sessiz değil."
        )
    elif coverage_strength == "insufficient_data":
        code = "low"
        reasons.append(
            f"Yeterli gözlem yok ({int(row['observation_count'])} < {min_observations}); "
            "sessizlik güvenilir değil."
        )
    elif coverage_strength == "weak":
        code = "low"
        reasons.append(
            f"Yapısal kapsama zayıf (baz ortalaması {float(row['baseline_mean']):.1f} < "
            f"{min_coverage_signal:.1f}); bölge zaten az raporluyor, sessizlik yanlış "
            "alarm olabilir."
        )
    elif sudden_drop:
        code = "high"
        reasons.append(
            "Önceden normal kapsama vardı ve okuma baz çizgisinin belirgin altında "
            f"(z={float(row['z_score']):.2f}); ani sessizlik gerçek acil durum "
            "işareti."
        )
    else:
        code = "medium"
        reasons.append(
            "Kapsama sağlam ve sessiz aday, ancak düşüş belirgin değil "
            f"(z={float(row['z_score']):.2f}); izlemeye değer."
        )

    labelled = dict(row)
    labelled["coverage_strength"] = coverage_strength
    labelled["sudden_drop"] = sudden_drop
    labelled["confidence_code"] = code
    labelled["confidence_label"] = (
        CONFIDENCE_LABELS[code] if code is not None else "Sessiz aday değil"
    )
    labelled["confidence_reasons"] = reasons
    return labelled


def silent_zone_confidence_report(
    settings: Any,
    *,
    source: Optional[str] = None,
    as_of: Optional[Any] = None,
    window_days: Optional[int] = None,
    confidence: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Silent candidates labelled high/medium/low confidence, most urgent first.

    ``confidence`` keeps only that tier (an unknown value is *not* silently
    swallowed: ``filter`` comes back ``None`` with ``requested_filter`` echo).
    ``limit`` clips the labelled listing while the summary always describes the
    whole candidate set.
    """
    base = baseline_report(
        settings, source=source, as_of=as_of, window_days=window_days
    )

    labelled = [classify_cell(cell, settings) for cell in base["cells"]]
    candidates = [row for row in labelled if row["candidate_silent"]]

    tier_rank = {code: index for index, code in enumerate(CONFIDENCE_ORDER)}
    candidates.sort(
        key=lambda r: (
            tier_rank.get(r["confidence_code"], len(CONFIDENCE_ORDER)),
            r["z_score"],
            r["region_key"],
        )
    )

    counts = {code: 0 for code in CONFIDENCE_ORDER}
    for row in candidates:
        if row["confidence_code"] in counts:
            counts[row["confidence_code"]] += 1
    weak_coverage = sum(
        1
        for row in candidates
        if row["coverage_strength"] in ("weak", "insufficient_data")
    )

    requested = confidence.strip().lower() if confidence else None
    known_filter = requested in CONFIDENCE_ORDER
    if requested and known_filter:
        listing = [row for row in candidates if row["confidence_code"] == requested]
    else:
        listing = candidates

    effective_limit: Optional[int] = None
    if limit is not None:
        if limit < 1:
            raise SilentZoneConfidenceError("limit 1 veya daha büyük olmalı")
        max_limit = _max_limit(settings)
        effective_limit = max(1, min(limit, max_limit))
        listing = listing[:effective_limit]

    return {
        "panel": "silent_zone_confidence",
        "generated_at": base["as_of"],
        "source_kind": base["source_kind"],
        "source_label": base["source_label"],
        "as_of": base["as_of"],
        "window_days": base["window_days"],
        "count": len(listing),
        "filter": requested if known_filter else None,
        "requested_filter": requested,
        "limit": effective_limit,
        "thresholds": {
            "min_coverage_signal": _min_coverage_signal(settings),
            "min_observations": _min_observations(settings),
            "strong_drop_z": _strong_drop_z(settings),
            "max_limit": _max_limit(settings),
        },
        "summary": {
            "cell_count": base["cell_count"],
            "candidate_silent_count": len(candidates),
            "high_confidence": counts["high"],
            "medium_confidence": counts["medium"],
            "low_confidence": counts["low"],
            "weak_coverage_candidates": weak_coverage,
        },
        "candidates": listing,
        "attribution": SILENT_ZONE_CONFIDENCE_ATTRIBUTION,
        "persistence": SILENT_ZONE_CONFIDENCE_PERSISTENCE,
        "synthetic": base["synthetic"],
        "synthetic_label": base.get("synthetic_label"),
    }


def silent_zone_confidence_config(settings: Any = None) -> dict[str, Any]:
    """Descriptive payload: the confidence ladder, its rules and thresholds."""
    cfg = settings if settings is not None else _NullSettings()
    return {
        "ladder": [
            {
                "code": "high",
                "label": CONFIDENCE_LABELS["high"],
                "rule": "kapsama sağlam ve ani düşüş (z <= -strong_drop_z)",
            },
            {
                "code": "medium",
                "label": CONFIDENCE_LABELS["medium"],
                "rule": "kapsama sağlam ve sessiz aday, ancak düşüş belirgin değil",
            },
            {
                "code": "low",
                "label": CONFIDENCE_LABELS["low"],
                "rule": "yapısal kapsama zayıf veya yetersiz gözlem (yanlış alarm)",
            },
        ],
        "thresholds": {
            "min_coverage_signal": _min_coverage_signal(cfg),
            "min_observations": _min_observations(cfg),
            "strong_drop_z": _strong_drop_z(cfg),
            "max_limit": _max_limit(cfg),
        },
        "sort": "confidence (high, medium, low), z_score asc, region_key asc",
        "attribution": SILENT_ZONE_CONFIDENCE_ATTRIBUTION,
        "persistence": SILENT_ZONE_CONFIDENCE_PERSISTENCE,
        "synthetic": True,
    }


class _NullSettings:
    """Sentinel so ``silent_zone_confidence_config()`` works with no settings."""


__all__ = [
    "CONFIDENCE_LABELS",
    "CONFIDENCE_ORDER",
    "SILENT_ZONE_CONFIDENCE_ATTRIBUTION",
    "SILENT_ZONE_CONFIDENCE_PERSISTENCE",
    "SilentZoneConfidenceError",
    "classify_cell",
    "silent_zone_confidence_config",
    "silent_zone_confidence_report",
]
