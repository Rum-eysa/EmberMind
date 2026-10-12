"""EM-094 event & alert webhook tests (Epic E9).

The webhook layer lets an integrator push live-feed events (fire_event /
forecast / alert, EM-090) to an outbound endpoint instead of polling. These
tests pin: subscription registration with URL/event-type validation and secret
redaction, the deterministic HMAC-SHA256 signature over ``<timestamp>.<body>``,
the signed-request envelope preview, the fan-out dispatch (one ledger row per
matching enabled subscription), the simulated-failure path that schedules a
bounded exponential-backoff retry, ``retry_due`` re-attempt + exhaustion, the
delivery history ordering / filtering, and the HTTP endpoints (including the
404 on an unknown subscription and 400 on an invalid payload).
"""
import json

import pytest
from sqlalchemy import select

from src.models.live import LiveUpdate
from src.models.webhook import (
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    WebhookDelivery,
    WebhookSubscription,
)
from src.services.webhook_delivery import (
    SIGNATURE_HEADER,
    VALID_EVENT_TYPES,
    WEBHOOK_ATTRIBUTION,
    WEBHOOK_PERSISTENCE,
    WebhookError,
    build_envelope,
    create_subscription,
    delete_subscription,
    dispatch_event,
    list_deliveries,
    list_subscriptions,
    record_attempt,
    retry_due,
    signature_for,
    update_subscription,
    webhook_config,
    webhook_overview,
)


class _Settings:
    """Webhook bounds used across the service tests."""

    def __init__(self, *, max_subs=20, max_del=100, max_retries=3, backoff=30):
        self.WEBHOOK_MAX_SUBSCRIPTIONS = max_subs
        self.WEBHOOK_MAX_DELIVERIES = max_del
        self.WEBHOOK_MAX_RETRIES = max_retries
        self.WEBHOOK_BACKOFF_SECONDS = backoff


def _feed(session, *, kind="alert", event_key="evt-1", title="Risk", message="msg"):
    """Push one live-feed row of the given kind and return its id."""
    row = LiveUpdate(
        kind=kind,
        event_key=event_key,
        title=title,
        message=message,
        source="test",
        payload_json=json.dumps({"to_level": "kritik", "risk_index": 42}),
    )
    session.add(row)
    session.flush()
    return int(row.id)


def _sub(
    session,
    settings=None,
    *,
    name="ops",
    url="https://example.dev/hook",
    event_types=("alert",),
    secret="s3cr3t",
    enabled=True,
):
    """Create a subscription and return its ORM row (not the dict view)."""
    create_subscription(
        session,
        settings or _Settings(),
        name=name,
        url=url,
        event_types=list(event_types),
        secret=secret,
        enabled=enabled,
    )
    return session.scalars(
        select(WebhookSubscription).order_by(WebhookSubscription.id.desc())
    ).first()


# --------------------------------------------------------------------------
# subscription registration + validation
# --------------------------------------------------------------------------
def test_create_subscription_redacts_secret(session):
    session.flush()
    data = create_subscription(
        session,
        _Settings(),
        name="Ops Central",
        url="https://ops.example.dev/webhook",
        event_types=["alert", "fire_event"],
        secret="topsecret",
    )
    assert data["subscription_key"].startswith("whk-")
    assert data["event_types"] == ["alert", "fire_event"]
    assert data["enabled"] is True
    assert data["has_secret"] is True
    # The shared secret must never be echoed back through the API view.
    assert "secret" not in data
    assert "topsecret" not in json.dumps(data)


def test_create_subscription_rejects_bad_url(session):
    with pytest.raises(WebhookError):
        create_subscription(
            session, _Settings(), name="x", url="ftp://nope", event_types=["alert"]
        )


def test_create_subscription_requires_https_or_http_host(session):
    with pytest.raises(WebhookError):
        create_subscription(
            session, _Settings(), name="x", url="not a url", event_types=["alert"]
        )


def test_create_subscription_rejects_empty_event_types(session):
    with pytest.raises(WebhookError):
        create_subscription(
            session, _Settings(), name="x", url="https://a.dev/h", event_types=[]
        )


def test_create_subscription_rejects_unknown_event_type(session):
    with pytest.raises(WebhookError):
        create_subscription(
            session,
            _Settings(),
            name="x",
            url="https://a.dev/h",
            event_types=["meteor"],
        )


def test_create_subscription_rejects_empty_name(session):
    with pytest.raises(WebhookError):
        create_subscription(
            session,
            _Settings(),
            name="   ",
            url="https://a.dev/h",
            event_types=["alert"],
        )


def test_create_subscription_enforces_max(session):
    settings = _Settings(max_subs=2)
    for i in range(2):
        create_subscription(
            session,
            settings,
            name=f"s{i}",
            url="https://a.dev/h",
            event_types=["alert"],
        )
    with pytest.raises(WebhookError):
        create_subscription(
            session,
            settings,
            name="third",
            url="https://a.dev/h",
            event_types=["alert"],
        )


def test_list_subscriptions_counts_deliveries(session):
    settings = _Settings()
    sub = _sub(session, settings)
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert")
    session.flush()
    data = list_subscriptions(session, settings)
    assert data["count"] == 1
    assert data["subscriptions"][0]["delivery_count"] == 1
    assert data["attribution"] == WEBHOOK_ATTRIBUTION
    assert data["persistence"] == WEBHOOK_PERSISTENCE


# --------------------------------------------------------------------------
# signing + envelope preview
# --------------------------------------------------------------------------
def test_signature_is_deterministic_and_reproducible():
    sig_a = signature_for("secret", "2026-01-01T00:00:00Z", '{"a":1}')
    sig_b = signature_for("secret", "2026-01-01T00:00:00Z", '{"a":1}')
    sig_other = signature_for("different", "2026-01-01T00:00:00Z", '{"a":1}')
    assert sig_a == sig_b
    assert sig_a != sig_other
    assert len(sig_a) == 64  # hex sha256


def test_build_envelope_carries_signature_header(session):
    sub = _sub(session, _Settings(), secret="k0")
    row_id = _feed(session, kind="alert")
    feed = session.scalars(select(LiveUpdate).where(LiveUpdate.id == row_id)).first()
    env = build_envelope(sub, feed, timestamp="2026-01-01T00:00:00Z")
    assert env["method"] == "POST"
    assert env["url"] == sub.url
    header = env["headers"][SIGNATURE_HEADER]
    assert header.startswith("t=2026-01-01T00:00:00Z,v1=")
    body = env["body"]
    expected = signature_for("k0", "2026-01-01T00:00:00Z", body)
    assert header.endswith(expected)
    # The body is valid JSON carrying the notification payload.
    parsed = json.loads(body)
    assert parsed["event_type"] == "alert"
    assert parsed["notification"]["id"] == row_id


# --------------------------------------------------------------------------
# dispatch fan-out
# --------------------------------------------------------------------------
def test_dispatch_delivers_to_matching_subscriptions(session):
    settings = _Settings()
    _sub(session, settings, name="a", event_types=("alert",))
    _sub(session, settings, name="b", event_types=("alert", "fire_event"))
    _feed(session, kind="alert")
    result = dispatch_event(session, settings, "alert")
    assert result["subscriptions_matched"] == 2
    assert result["created"] == 2
    assert all(d["status"] == DELIVERY_DELIVERED for d in result["deliveries"])
    assert all(d["http_status"] == 200 for d in result["deliveries"])


def test_dispatch_skips_uninterested_and_disabled(session):
    settings = _Settings()
    _sub(session, settings, name="only-fire", event_types=("fire_event",))
    _sub(session, settings, name="disabled", event_types=("alert",), enabled=False)
    _feed(session, kind="alert")
    result = dispatch_event(session, settings, "alert")
    assert result["subscriptions_matched"] == 0
    assert result["created"] == 0


def test_dispatch_dry_run_writes_nothing(session):
    settings = _Settings()
    _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    result = dispatch_event(session, settings, "alert", dry_run=True)
    assert result["dry_run"] is True
    assert len(result["previews"]) == 1
    assert result["created"] == 0
    # No ledger rows persisted on a preview.
    assert list_deliveries(session, settings)["returned_count"] == 0


def test_dispatch_unknown_event_type_raises(session):
    with pytest.raises(WebhookError):
        dispatch_event(session, _Settings(), "meteor")


def test_dispatch_simulated_failure_schedules_retry(session):
    settings = _Settings(max_retries=3, backoff=30)
    sub = _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    result = dispatch_event(
        session, settings, "alert", simulate_fail_for=sub.subscription_key
    )
    delivery = result["deliveries"][0]
    assert delivery["status"] == DELIVERY_FAILED
    assert delivery["attempt"] == 1
    assert delivery["next_retry_at"] is not None


# --------------------------------------------------------------------------
# retry + record_attempt
# --------------------------------------------------------------------------
def test_retry_due_success_clears_and_bumps_attempt(session):
    settings = _Settings()
    sub = _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert", simulate_fail_for=sub.subscription_key)
    result = retry_due(session, settings)
    assert len(result["retried"]) == 1
    row = result["retried"][0]
    assert row["status"] == DELIVERY_DELIVERED
    assert row["attempt"] == 2
    assert row["next_retry_at"] is None


def test_retry_reschedules_with_wider_backoff(session):
    settings = _Settings(max_retries=3, backoff=30)
    sub = _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert", simulate_fail_for=sub.subscription_key)
    first = retry_due(session, settings, simulate_fail=True)
    row = first["retried"][0]
    assert row["attempt"] == 2
    assert row["status"] == DELIVERY_FAILED
    assert row["next_retry_at"] is not None


def test_retry_exhausts_at_max_budget(session):
    settings = _Settings(max_retries=2, backoff=1)
    sub = _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    # attempt 1 fails with a retry scheduled (1 < 2).
    dispatch_event(session, settings, "alert", simulate_fail_for=sub.subscription_key)
    # retry bumps to attempt 2 which equals the budget -> next simulate marks exhausted.
    retry_due(session, settings, simulate_fail=True)
    final = retry_due(session, settings, simulate_fail=True)
    assert len(final["exhausted"]) == 1
    assert final["exhausted"][0]["attempt"] == 2
    assert final["exhausted"][0]["next_retry_at"] is None


def test_record_attempt_success_closes_delivery(session):
    settings = _Settings()
    sub = _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert", simulate_fail_for=sub.subscription_key)
    delivery_key = list_deliveries(session, settings)["deliveries"][0]["delivery_key"]
    result = record_attempt(
        session, settings, delivery_key, success=True, http_status=201
    )
    assert result["status"] == DELIVERY_DELIVERED
    assert result["http_status"] == 201


def test_record_attempt_unknown_raises(session):
    with pytest.raises(WebhookError):
        record_attempt(session, _Settings(), "dlv-nope", success=True)


# --------------------------------------------------------------------------
# delivery history
# --------------------------------------------------------------------------
def test_list_deliveries_newest_first_with_status_counts(session):
    settings = _Settings()
    sub = _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert")  # delivered
    dispatch_event(session, settings, "alert", simulate_fail_for=sub.subscription_key)
    data = list_deliveries(session, settings)
    assert data["returned_count"] == 2
    assert data["total_matching"] == 2
    assert data["by_status"][DELIVERY_DELIVERED] == 1
    assert data["by_status"][DELIVERY_FAILED] == 1
    # newest first: the failing (second) dispatch is at the head.
    assert data["deliveries"][0]["status"] == DELIVERY_FAILED


def test_list_deliveries_filter_by_subscription(session):
    settings = _Settings()
    sub_a = _sub(session, settings, name="a", event_types=("alert",))
    sub_b = _sub(session, settings, name="b", event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert")
    only_b = list_deliveries(session, settings, subscription_key=sub_b.subscription_key)
    assert only_b["returned_count"] == 1
    assert only_b["deliveries"][0]["subscription_key"] == sub_b.subscription_key
    assert sub_a.subscription_key != sub_b.subscription_key


# --------------------------------------------------------------------------
# update + delete
# --------------------------------------------------------------------------
def test_update_subscription_disables_and_revalidates(session):
    settings = _Settings()
    sub = _sub(session, settings, event_types=("alert",))
    updated = update_subscription(
        session,
        settings,
        sub.subscription_key,
        enabled=False,
        event_types=["fire_event"],
    )
    assert updated["enabled"] is False
    assert updated["event_types"] == ["fire_event"]
    with pytest.raises(WebhookError):
        update_subscription(session, settings, sub.subscription_key, url="bad")


def test_delete_subscription_keeps_history(session):
    settings = _Settings()
    sub = _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert")
    delete_subscription(session, settings, sub.subscription_key)
    assert list_subscriptions(session, settings)["count"] == 0
    # The delivery ledger survives as an audit trail.
    assert list_deliveries(session, settings)["returned_count"] == 1


def test_overview_combines_subscriptions_and_recent(session):
    settings = _Settings()
    _sub(session, settings, event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert")
    data = webhook_overview(session, settings)
    assert data["panel"] == "webhooks"
    assert data["count"] == 1
    assert data["summary"][DELIVERY_DELIVERED] == 1
    assert len(data["recent_deliveries"]) == 1


def test_config_lists_kinds_and_bounds():
    cfg = webhook_config(_Settings(max_retries=5, backoff=60))
    assert cfg["event_types"] == list(VALID_EVENT_TYPES)
    assert cfg["signature_header"] == SIGNATURE_HEADER
    assert cfg["max_retries"] == 5
    assert cfg["backoff_seconds"] == 60


# --------------------------------------------------------------------------
# HTTP endpoints
# --------------------------------------------------------------------------
def test_endpoint_create_and_list(api, client, session):
    session.commit()
    resp = client.post(
        "/api/v1/webhooks/subscriptions",
        json={
            "name": "Ops",
            "url": "https://ops.example.dev/hook",
            "event_types": ["alert"],
            "secret": "abc",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["subscription"]["has_secret"] is True
    listing = client.get("/api/v1/webhooks/subscriptions").json()
    assert listing["count"] == 1


def test_endpoint_dispatch_and_history(api, client, session):
    _sub(session, _Settings(), event_types=("alert",))
    _feed(session, kind="alert")
    session.commit()
    disp = client.post("/api/v1/webhooks/dispatch", json={"event_type": "alert"})
    assert disp.status_code == 200
    assert disp.json()["created"] == 1
    hist = client.get("/api/v1/webhooks/deliveries").json()
    assert hist["returned_count"] == 1


def test_endpoint_invalid_subscription_is_400(api, client, session):
    session.commit()
    resp = client.post(
        "/api/v1/webhooks/subscriptions",
        json={"name": "x", "url": "ftp://bad", "event_types": ["alert"]},
    )
    assert resp.status_code == 400


def test_endpoint_unknown_subscription_update_is_404(api, client, session):
    session.commit()
    resp = client.put(
        "/api/v1/webhooks/subscriptions/whk-missing", json={"enabled": False}
    )
    assert resp.status_code == 404


def test_endpoint_config(api, client):
    resp = client.get("/api/v1/webhooks/config")
    assert resp.status_code == 200
    assert "fire_event" in resp.json()["event_types"]


def test_delivery_row_snapshot_survives_edit(session):
    """The ledger denormalises the URL so history is stable after edits."""
    settings = _Settings()
    sub = _sub(session, settings, url="https://old.dev/h", event_types=("alert",))
    _feed(session, kind="alert")
    dispatch_event(session, settings, "alert")
    update_subscription(
        session, settings, sub.subscription_key, url="https://new.dev/h"
    )
    row = session.query(WebhookDelivery).first()
    assert row.url == "https://old.dev/h"
