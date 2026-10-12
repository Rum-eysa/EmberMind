"""EM-045 recommendation-engine value metric tests.

The engine must attach an *expected risk reduction* to every ranked proposal:
the drop in the event's peak EM-029 risk index if that single unit is dedicated
to the incident instead of held in reserve, honouring its arrival time. These
tests pin the pure marginal math (fast vs slow unit, peak-horizon choice, the
not-measurable guards), the proposal enrichment (reachable vs unreachable vs
non-suppression kinds) and the HTTP surface.
"""
import pytest

from src.services.recommendation_engine import (
    ENGINE_ATTRIBUTION,
    enrich_proposals,
    marginal_risk_reduction,
)
from src.services.risk_index import RiskIndexError
from src.services.positioning import build_proposals
from tests.unit.test_recommendation_impact import (
    _Settings,
    _seed_two_crews,
)

# A single measurable horizon: demand_ha_h(3.0, 60) == 3.0 ha/h.
_FC_60 = {60: 3.0}


# ------------------------------------------------------- pure marginal math ---


def test_fast_capable_unit_reduces_peak_risk():
    # total 4.0 ha/h, holding the 2.0 unit back leaves 2.0; arriving by T+10 it
    # counts at the 60-minute horizon -> 1.5 risk falls to 0.75, a 0.75 drop.
    value = marginal_risk_reduction(_FC_60, 2.0, 10.0, 4.0)
    assert value == pytest.approx(0.75)


def test_reduction_measured_at_the_worst_without_horizon():
    # T+30 is the peak without the unit (demand 4.0 / 2.0 = 2.0); with it the
    # same horizon is 4.0 / 4.0 = 1.0, so the reported drop is 1.0.
    fc = {30: 2.0, 60: 2.0}
    value = marginal_risk_reduction(fc, 2.0, 5.0, 4.0)
    assert value == pytest.approx(1.0)


def test_slow_unit_arriving_after_peak_helps_that_moment_nothing():
    # ETA 999 is past every horizon, so at the worst horizon the unit is not on
    # station and the with-side risk equals the without-side -> 0.0 reduction.
    value = marginal_risk_reduction(_FC_60, 2.0, 999.0, 4.0)
    assert value == 0.0


def test_not_measurable_cases_return_none():
    # no baseline capacity, no unit capacity, no positive margin, no forecast.
    assert marginal_risk_reduction(_FC_60, 2.0, 5.0, 0.0) is None
    assert marginal_risk_reduction(_FC_60, 0.0, 5.0, 4.0) is None
    assert marginal_risk_reduction(_FC_60, 4.0, 5.0, 4.0) is None
    assert marginal_risk_reduction({}, 2.0, 5.0, 4.0) is None


# ---------------------------------------------------------- enrichment ------


def _proposal(key, kind="suppression_resource", rtype="crew", reachable=True, eta=5.0):
    return {
        "resource_key": key,
        "kind": kind,
        "resource_type": rtype,
        "reachable": reachable,
        "eta_minutes": eta if reachable else None,
    }


def test_enrich_scores_reachable_and_blanks_the_rest(session):
    _seed_two_crews(session)  # crew_near reachable, crew_island unreachable
    proposals = build_proposals(session, _Settings(), "EVT-IMP")
    enrich_proposals(session, _Settings(), "EVT-IMP", proposals)
    by_key = {p["resource_key"]: p for p in proposals}
    # The road-reachable crew is worth exactly a 1.0 peak-risk drop here.
    assert by_key["crew_near"]["expected_risk_reduction"] == pytest.approx(1.0)
    # Unreachable and non-suppression origins carry no expected value.
    assert by_key["crew_island"]["reachable"] is False
    assert by_key["crew_island"]["expected_risk_reduction"] is None


def test_enrich_blanks_crew_bases(session):
    _seed_two_crews(session)
    proposals = [_proposal("base-1", kind="crew_base", rtype="crew")]
    enrich_proposals(session, _Settings(), "EVT-IMP", proposals)
    assert proposals[0]["expected_risk_reduction"] is None


def test_enrich_unknown_event_raises(session):
    with pytest.raises(RiskIndexError):
        enrich_proposals(session, _Settings(), "NOPE", [])


# --------------------------------------------------------------- endpoint ---


def test_endpoint_exposes_expected_risk_reduction(client, session):
    _seed_two_crews(session)
    session.commit()
    body = client.get("/api/v1/positioning/proposals?event_key=EVT-IMP").json()
    assert body["value_metric"]["field"] == "expected_risk_reduction"
    assert body["value_metric"]["attribution"] == ENGINE_ATTRIBUTION
    by_key = {p["resource_key"]: p for p in body["proposals"]}
    # Sink mode keeps only reachable origins, each now value-scored.
    assert by_key["crew_near"]["expected_risk_reduction"] == pytest.approx(1.0)
    assert "crew_island" not in by_key
