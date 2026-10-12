"""EM-043 seasonally-adjusted signal baseline tests (Epic E4).

EM-043 learns hour-of-day and day-of-week factors, deseasonalises the signal and
scores the residual against the *seasonal* normal instead of the flat one, so a
structurally quiet night/weekend is not a false "silent" candidate. These tests
pin the deterministic diurnal feed, the two-way factor learning (hourly vs a
daily-only degrade), the flat-vs-seasonal false-alarm comparison (before/after),
the report ordering/filters, the daily refresh shape and the read-only HTTP
endpoints.
"""
from datetime import date, timedelta

import pytest

from src.services.signal_baseline import SignalSource, monitoring_cells
from src.services.signal_baseline_seasonal import (
    DAYS_IN_WEEK,
    DIURNAL_PROFILE,
    DIURNAL_SOURCE_KIND,
    HOURS_IN_DAY,
    SEASONAL_ATTRIBUTION,
    SEASONAL_PERSISTENCE,
    SEASONALITY_DIMENSIONS,
    SignalSeasonalError,
    SyntheticDiurnalSource,
    TURKISH_WEEKDAYS,
    available_seasonal_source_kinds,
    learn_seasonal_factors,
    refresh_daily_baselines,
    resolve_seasonal_source,
    seasonal_baseline_config,
    seasonal_cell,
    seasonal_report,
)

_AS_OF = date(2026, 8, 15)


class _Settings:
    """Config stub; every seasonal key has a service default so this stays empty."""

    def __init__(self, **overrides):
        for key, value in overrides.items():
            setattr(self, key, value)


class _FakeHourly(SignalSource):
    """Deterministic hourly feed: quiet early hours, busy otherwise.

    A stable per-hour profile plus small deterministic day/hour jitter, so the
    two-way decomposition recovers the hour factor exactly. ``dip`` overrides a
    single ``(day, hour)`` reading to place an artificial anomaly. ``weekend``
    defaults to 1.0 so weekday effects do not muddy the hour assertions.
    """

    kind = "fake_hourly"
    label = "Sahte saatlik akış"
    synthetic = False
    has_hourly = True

    def __init__(self, profile, base=100.0, weekend=1.0, dip=None):
        self._profile = profile
        self._base = base
        self._weekend = weekend
        self._dip = dip

    def hourly_signal(self, region_key: str, day: date, hour: int) -> float:
        bounded = hour % HOURS_IN_DAY
        if self._dip is not None and day == self._dip[0] and bounded == self._dip[1]:
            return self._dip[2]
        factor = self._weekend if day.weekday() >= 5 else 1.0
        jitter = 1.0 + 0.03 * ((day.toordinal() + bounded) % 5 - 2)
        return round(self._base * self._profile[bounded] * factor * jitter, 3)

    def daily_signal(self, region_key: str, day: date) -> float:
        hours = [self.hourly_signal(region_key, day, h) for h in range(HOURS_IN_DAY)]
        return round(sum(hours) / len(hours), 3)


_NIGHT_PROFILE = {h: (0.2 if h < 6 else 1.0) for h in range(HOURS_IN_DAY)}


# --------------------------------------------------------------------------- #
# Diurnal synthetic source: determinism + real hour structure
# --------------------------------------------------------------------------- #
def test_diurnal_source_is_deterministic_and_hourly():
    source = SyntheticDiurnalSource()
    assert source.has_hourly is True
    first = source.hourly_signal("SB-R1C1", _AS_OF, 12)
    second = source.hourly_signal("SB-R1C1", _AS_OF, 12)
    assert first == second > 0


def test_diurnal_source_night_is_quietest_hour():
    source = SyntheticDiurnalSource()

    # Averages over a week remove jitter; the deepest night must be the lowest.
    def avg_hour(hour):
        days = [date(2026, 8, d) for d in range(1, 22)]
        return sum(source.hourly_signal("SB-R1C1", d, hour) for d in days) / len(days)

    assert avg_hour(2) < avg_hour(6) < avg_hour(12)


def test_diurnal_profile_peaks_midday_and_bottoms_at_night():
    assert len(DIURNAL_PROFILE) == HOURS_IN_DAY
    assert all(value > 0 for value in DIURNAL_PROFILE)
    # The quietest hour is in the deep night; the busiest is around midday/afternoon.
    assert min(range(HOURS_IN_DAY), key=DIURNAL_PROFILE.__getitem__) < 6
    assert max(range(HOURS_IN_DAY), key=DIURNAL_PROFILE.__getitem__) in range(9, 18)


# --------------------------------------------------------------------------- #
# Source resolution
# --------------------------------------------------------------------------- #
def test_resolve_source_defaults_to_diurnal():
    source = resolve_seasonal_source(None, _Settings())
    assert source.kind == DIURNAL_SOURCE_KIND


def test_resolve_source_is_case_insensitive():
    source = resolve_seasonal_source("SYNTHETIC_DIURNAL", _Settings())
    assert source.kind == DIURNAL_SOURCE_KIND


def test_resolve_source_accepts_em035_daily_kind():
    source = resolve_seasonal_source("synthetic_communication", _Settings())
    assert getattr(source, "has_hourly", False) is False


def test_resolve_source_unknown_kind_raises():
    with pytest.raises(SignalSeasonalError, match="bilinmeyen mevsimsel"):
        resolve_seasonal_source("uydu", _Settings())


def test_available_kinds_include_diurnal_and_daily():
    kinds = available_seasonal_source_kinds()
    assert DIURNAL_SOURCE_KIND in kinds
    assert "synthetic_communication" in kinds
    assert kinds == sorted(kinds)


# --------------------------------------------------------------------------- #
# Seasonal factor learning
# --------------------------------------------------------------------------- #
def test_learn_recovers_hour_structure():
    days = [_AS_OF - __import__("datetime").timedelta(o) for o in range(30, 0, -1)]
    learned = learn_seasonal_factors(_FakeHourly(_NIGHT_PROFILE), "SB-R1C1", days, 3)
    assert learned["hourly_available"] is True
    assert learned["hour_factors"][3] < learned["hour_factors"][12]
    assert learned["sample_count"] == 30 * HOURS_IN_DAY


def test_learn_daily_source_collapses_hour_factors():
    # A daily-only source contributes one sample per day -> neutral hour factors.
    days = [_AS_OF - __import__("datetime").timedelta(o) for o in range(30, 0, -1)]
    learned = learn_seasonal_factors(SyntheticCommunicationDaily(), "SB-R1C1", days, 3)
    assert learned["hourly_available"] is False
    assert all(abs(f - 1.0) < 1e-9 for f in learned["hour_factors"])


def test_learn_factors_are_mean_normalised():
    days = [_AS_OF - __import__("datetime").timedelta(o) for o in range(20, 0, -1)]
    learned = learn_seasonal_factors(_FakeHourly(_NIGHT_PROFILE), "SB-R2C2", days, 12)
    positive = [f for f in learned["hour_factors"] if f > 0]
    assert sum(positive) / len(positive) == pytest.approx(1.0, abs=0.05)


class SyntheticCommunicationDaily(SignalSource):
    """A non-hourly source (weekday-only seasonality) for the degrade test."""

    kind = "fake_daily"
    label = "Sahte günlük akış"
    synthetic = False

    def daily_signal(self, region_key: str, day: date) -> float:
        weekend = 0.7 if day.weekday() >= 5 else 1.0
        return round(100.0 * weekend, 3)


# --------------------------------------------------------------------------- #
# Flat (before) vs seasonal (after) false-alarm comparison
# --------------------------------------------------------------------------- #
def _cell():
    return monitoring_cells(_Settings())[0]


def test_night_quiet_is_a_flat_alarm_removed_by_seasonality():
    source = _FakeHourly(_NIGHT_PROFILE)
    row = seasonal_cell(_Settings(), _cell(), source, _AS_OF, 3, 30, 1.5)
    # Night silence looks anomalous against a flat mean but is normal for the hour.
    assert row["candidate_flat"] is True
    assert row["candidate_seasonal"] is False
    assert row["false_alarm_removed"] is True
    assert row["z_flat"] < row["z_seasonal"]


def test_midday_quiet_is_a_new_seasonal_candidate():
    # A quiet midday reading is invisible to the flat baseline but the seasonal
    # model expects busy daytime, so it is flagged only after deseasonalising.
    source = _FakeHourly(_NIGHT_PROFILE, dip=(_AS_OF, 12, 40.0))
    row = seasonal_cell(_Settings(), _cell(), source, _AS_OF, 12, 30, 1.5)
    assert row["candidate_seasonal"] is True
    assert row["candidate_flat"] is False
    assert row["false_alarm_removed"] is False


def test_seasonal_cell_carries_factors_and_labels():
    source = _FakeHourly(_NIGHT_PROFILE)
    row = seasonal_cell(_Settings(), _cell(), source, _AS_OF, 3, 30, 1.5)
    assert row["region_key"] == _cell().region_key
    assert row["weekday_label"] == TURKISH_WEEKDAYS[_AS_OF.weekday()]
    assert row["check_hour"] == 3
    assert row["hour_factor"] > 0 and row["weekday_factor"] > 0
    assert row["seasonal_expected"] > 0


def test_invalid_night_hour_raises():
    with pytest.raises(SignalSeasonalError, match="geçersiz saat"):
        seasonal_report(_Settings(), as_of=_AS_OF, hour=24)


# --------------------------------------------------------------------------- #
# Report shape, ordering, filters
# --------------------------------------------------------------------------- #
def test_report_summary_counts_flat_vs_seasonal():
    report = seasonal_report(_Settings(), source=DIURNAL_SOURCE_KIND, as_of=_AS_OF)
    assert report["panel"] == "signal_baseline_seasonal"
    assert report["persistence"] == SEASONAL_PERSISTENCE
    assert report["attribution"] == SEASONAL_ATTRIBUTION
    assert report["seasonality_dimensions"] == list(SEASONALITY_DIMENSIONS)
    assert report["hourly_available"] is True
    assert report["cell_count"] == len(monitoring_cells(_Settings()))
    assert report["false_alarms_removed"] >= 0


def test_report_orders_seasonal_candidates_first():
    report = seasonal_report(_Settings(), source=DIURNAL_SOURCE_KIND, as_of=_AS_OF)
    keys = [
        (not row["candidate_seasonal"], row["z_seasonal"], row["region_key"])
        for row in report["cells"]
    ]
    assert keys == sorted(keys)


def test_report_region_filter_narrows():
    cell = _cell()
    report = seasonal_report(_Settings(), as_of=_AS_OF, region_key=cell.region_key)
    assert report["cell_count"] == 1
    assert report["cells"][0]["region_key"] == cell.region_key
    missing = seasonal_report(_Settings(), as_of=_AS_OF, region_key="YOK")
    assert missing["cell_count"] == 0


def test_report_limit_pages_cells():
    report = seasonal_report(_Settings(), as_of=_AS_OF, limit=4)
    assert len(report["cells"]) == 4
    assert report["cell_count"] == len(monitoring_cells(_Settings()))


def test_report_daily_only_source_has_no_hour_seasonality():
    report = seasonal_report(
        _Settings(), source="synthetic_communication", as_of=_AS_OF
    )
    assert report["hourly_available"] is False
    assert all(abs(row["hour_factor"] - 1.0) < 1e-9 for row in report["cells"])


# --------------------------------------------------------------------------- #
# Daily refresh
# --------------------------------------------------------------------------- #
def test_refresh_recomputes_every_cell():
    result = refresh_daily_baselines(_Settings(), as_of=_AS_OF)
    assert result["panel"] == "signal_baseline_seasonal"
    assert result["refresh_interval_days"] == 1
    assert result["persistence"] == SEASONAL_PERSISTENCE
    assert result["recomputed_cells"] == len(monitoring_cells(_Settings()))
    sample = result["cells"][0]
    assert set(sample) >= {
        "region_key",
        "hour_factor",
        "weekday_factor",
        "seasonal_expected",
        "refreshed_for",
    }
    assert sample["refreshed_for"] == _AS_OF.isoformat()


# --------------------------------------------------------------------------- #
# Config catalogue
# --------------------------------------------------------------------------- #
def test_config_catalogues_dimensions_and_refresh():
    cfg = seasonal_baseline_config()
    assert DIURNAL_SOURCE_KIND in cfg["sources"]["available"]
    assert cfg["hours_in_day"] == HOURS_IN_DAY
    assert len(cfg["weekdays"]) == DAYS_IN_WEEK
    assert cfg["seasonality_dimensions"] == list(SEASONALITY_DIMENSIONS)
    assert cfg["refresh"]["interval_days"] == 1
    assert cfg["persistence"] == SEASONAL_PERSISTENCE
    assert cfg["cell_count"] == len(monitoring_cells(_Settings()))


def test_config_honours_window_bounds():
    cfg = seasonal_baseline_config(_Settings())
    assert cfg["window_days"]["min"] <= cfg["window_days"]["default"]
    assert cfg["window_days"]["default"] <= cfg["window_days"]["max"]


# --------------------------------------------------------------------------- #
# HTTP endpoints (read-only)
# --------------------------------------------------------------------------- #
def test_endpoint_config(client):
    resp = client.get("/api/v1/signal-baseline-seasonal/config")
    assert resp.status_code == 200
    assert DIURNAL_SOURCE_KIND in resp.json()["sources"]["available"]


def test_endpoint_report(client):
    resp = client.get(
        "/api/v1/signal-baseline-seasonal",
        params={"as_of": "2026-08-15", "hour": "3"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "signal_baseline_seasonal"
    assert body["as_of"] == "2026-08-15"
    assert body["night_check_hour"] == 3
    assert len(body["cells"]) == len(monitoring_cells(_Settings()))


def test_endpoint_refresh(client):
    resp = client.get(
        "/api/v1/signal-baseline-seasonal/refresh", params={"as_of": "2026-08-15"}
    )
    assert resp.status_code == 200
    assert resp.json()["recomputed_cells"] >= 1


def test_endpoint_rejects_bad_as_of(client):
    resp = client.get(
        "/api/v1/signal-baseline-seasonal", params={"as_of": "15-08-2026"}
    )
    assert resp.status_code == 400
    assert "YYYY-MM-DD" in resp.json()["detail"]["error"]


def test_endpoint_rejects_unknown_source(client):
    resp = client.get("/api/v1/signal-baseline-seasonal", params={"source": "radar"})
    assert resp.status_code == 400
    assert "bilinmeyen mevsimsel" in resp.json()["detail"]["error"]


def test_endpoint_rejects_out_of_range_hour(client):
    resp = client.get("/api/v1/signal-baseline-seasonal", params={"hour": "24"})
    assert resp.status_code == 422
