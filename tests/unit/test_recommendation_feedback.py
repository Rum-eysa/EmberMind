"""EM-054 recommendation accept/reject feedback analytics tests.

The feedback loop is a read-only aggregation over the EM-047 decision audit.
These tests seed ``recommendation_decisions`` rows directly (accept / reject /
edit, plus a ``release`` lifecycle row that must be ignored) and pin the rates,
the per-type breakdown, the most-rejected ranking, the reason counts, the
resource-type snapshot fallback to inventory, the event-scope filter, the
improvement-idea heuristics and the HTTP surface.
"""
import json

from src.models.inventory import SuppressionResource
from src.models.recommendation import RecommendationDecision
from src.services.recommendation_feedback import FEEDBACK_PANEL, feedback_summary

_SEQ = [0]


def _decision(
    session,
    action,
    *,
    event_key="EVT-1",
    resource_key="RES-1",
    resource_type="crew",
    reason=None,
    with_type=True,
    commit=False,
):
    _SEQ[0] += 1
    detail = {"name": resource_key}
    if with_type:
        detail["resource_type"] = resource_type
    row = RecommendationDecision(
        decision_key=f"D-{_SEQ[0]}",
        event_key=event_key,
        proposal_id=f"prop-{_SEQ[0]}",
        resource_key=resource_key,
        action=action,
        reason=reason,
        decided_by="op",
        detail_json=json.dumps(detail),
        resource_status_before="available",
        resource_status_after="en_route"
        if action in ("accept", "edit")
        else "available",
    )
    session.add(row)
    if commit:
        session.commit()
    else:
        session.flush()
    return row


# ------------------------------------------------------------- rates ------


def test_overall_accept_reject_edit_rates(session):
    for _ in range(2):
        _decision(session, "accept")
    for _ in range(3):
        _decision(session, "reject", reason="yavaş")
    _decision(session, "edit")
    result = feedback_summary(session, None)
    assert result["panel"] == FEEDBACK_PANEL
    assert result["scope"] == "all"
    assert result["totals"] == {"accept": 2, "reject": 3, "edit": 1, "decisions": 6}
    assert result["rates"]["accept_rate"] == 0.333
    assert result["rates"]["reject_rate"] == 0.5
    assert result["rates"]["edit_rate"] == 0.167


def test_release_rows_are_excluded(session):
    _decision(session, "accept")
    _decision(session, "reject")
    # EM-053 release lifecycle must not pollute the decision feedback.
    _decision(session, "release", resource_key="RES-9", resource_type="crew")
    result = feedback_summary(session, None)
    assert result["totals"]["decisions"] == 2


def test_no_decisions_yields_null_rates_and_seed_idea(session):
    result = feedback_summary(session, None)
    assert result["totals"]["decisions"] == 0
    assert result["rates"] == {
        "accept_rate": None,
        "reject_rate": None,
        "edit_rate": None,
    }
    assert result["by_resource_type"] == []
    assert result["most_rejected_types"] == []
    assert any("operatör kararı yok" in idea for idea in result["improvement_ideas"])


# ----------------------------------------------------------- per-type -----


def test_most_rejected_type_and_breakdown(session):
    _decision(session, "accept", resource_type="helicopter", resource_key="H-1")
    _decision(session, "accept", resource_type="helicopter", resource_key="H-2")
    for i in range(3):
        _decision(session, "reject", resource_type="crew", resource_key=f"C-{i}")
    result = feedback_summary(session, None)
    by_type = {row["resource_type"]: row for row in result["by_resource_type"]}
    assert by_type["crew"]["reject"] == 3
    assert by_type["crew"]["reject_rate"] == 1.0
    assert by_type["helicopter"]["reject_rate"] == 0.0
    assert result["most_rejected_types"][0]["resource_type"] == "crew"
    # A type rejected at/above the alert threshold is called out for tuning.
    assert any("crew" in idea for idea in result["improvement_ideas"])


def test_reason_counts_map_to_backlog_ideas(session):
    _decision(session, "reject", reason="çok yavaş gelir", resource_key="A")
    _decision(session, "reject", reason="çok yavaş gelir", resource_key="B")
    _decision(session, "reject", reason="kaynak uzak", resource_key="C")
    result = feedback_summary(session, None)
    reasons = {r["reason"]: r["count"] for r in result["rejection_reasons"]}
    assert reasons["çok yavaş gelir"] == 2
    assert reasons["kaynak uzak"] == 1
    joined = " ".join(result["improvement_ideas"])
    assert "ETA" in joined or "Varış süresi" in joined
    assert "Mesafe" in joined or "menzil" in joined.lower()


def test_resource_type_falls_back_to_inventory(session):
    # A decision recorded without a resource_type snapshot resolves via inventory.
    session.add(
        SuppressionResource(
            resource_key="RES-INV",
            name="RES-INV",
            resource_type="helicopter",
            latitude=38.0,
            longitude=27.0,
            status="available",
            capacity=1.0,
        )
    )
    _decision(
        session,
        "reject",
        resource_key="RES-INV",
        with_type=False,
        reason="gece uçuşu yok",
    )
    result = feedback_summary(session, None)
    assert result["by_resource_type"][0]["resource_type"] == "helicopter"


# ---------------------------------------------------------- event scope ---


def test_event_key_scopes_the_analysis(session):
    _decision(session, "accept", event_key="EVT-A")
    _decision(session, "reject", event_key="EVT-A")
    _decision(session, "reject", event_key="EVT-B")
    scoped = feedback_summary(session, "EVT-A")
    assert scoped["scope"] == "EVT-A"
    assert scoped["totals"]["decisions"] == 2
    assert scoped["totals"]["reject"] == 1


# ------------------------------------------------------------- endpoint ---


def test_feedback_endpoint(client, session):
    _decision(session, "accept", commit=False)
    _decision(session, "reject", reason="menzil aşımı", resource_key="R2")
    session.commit()
    body = client.get("/api/v1/recommendations/feedback").json()
    assert body["panel"] == FEEDBACK_PANEL
    assert body["totals"]["decisions"] == 2
    assert body["source"].startswith("recommendation_decisions")


def test_feedback_endpoint_scoped_and_config(client, session):
    _decision(session, "accept", event_key="EVT-SC")
    _decision(session, "reject", event_key="EVT-OTHER", resource_key="R2")
    session.commit()
    scoped = client.get("/api/v1/recommendations/feedback?event_key=EVT-SC").json()
    assert scoped["totals"]["decisions"] == 1
    cfg = client.get("/api/v1/recommendations/feedback/config").json()
    assert cfg["actions"] == ["accept", "reject", "edit"]
    assert cfg["excludes"] == ["release"]
    assert "improvement_ideas" in cfg["measures"]


# ------------------------------------------------------------------ ui ----


def test_ui_wires_feedback_panel():
    from pathlib import Path

    html = Path("src/static/operator_map.html").read_text(encoding="utf-8")
    assert "toggleFeedback" in html
    assert "loadFeedback" in html
    assert "renderFeedback" in html
    assert "positioning-feedback" in html
    assert "/api/v1/recommendations/feedback" in html
