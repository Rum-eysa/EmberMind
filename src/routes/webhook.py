"""Event & alert webhook endpoints (EM-094, Epic E9).

Registers outbound webhook subscriptions (URL + event types + signing secret),
previews a signed request, fans the newest live-feed events out to matching
subscribers, records transport outcomes, retries due deliveries, and exposes the
durable delivery history.
"""
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.webhook_delivery import (
    WebhookError,
    build_envelope_preview,
    create_subscription,
    delete_subscription,
    dispatch_event,
    list_deliveries,
    list_subscriptions,
    record_attempt,
    retry_due,
    update_subscription,
    webhook_config,
    webhook_overview,
)


class SubscriptionRequest(BaseModel):
    """Create payload for an outbound webhook subscription."""

    name: str
    url: str
    event_types: list[str]
    secret: Optional[str] = None
    enabled: bool = True


class SubscriptionUpdateRequest(BaseModel):
    """Partial edit payload for a webhook subscription."""

    name: Optional[str] = None
    url: Optional[str] = None
    event_types: Optional[list[str]] = None
    secret: Optional[str] = None
    enabled: Optional[bool] = None


class DispatchRequest(BaseModel):
    """Fan-out payload: push the newest events of one kind to subscribers."""

    event_type: str
    limit: Optional[int] = None
    simulate_fail_for: Optional[str] = None
    dry_run: bool = False


class AttemptRequest(BaseModel):
    """Record the outcome of a delivery attempt (transport seam)."""

    success: bool
    http_status: Optional[int] = None
    error: Optional[str] = None


def _http_error(exc: WebhookError) -> HTTPException:
    """Map a service error to the right HTTP status (missing vs invalid)."""
    text = str(exc)
    status = 404 if "bulunamadı" in text else 400
    return HTTPException(status_code=status, detail={"status": "error", "error": text})


def register_webhook_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the EM-094 event & alert webhook endpoints."""

    @api.get("/api/v1/webhooks/config", tags=["panel"])
    def webhooks_config() -> dict[str, Any]:
        """Valid event kinds, signature scheme, bounds and defaults."""
        return webhook_config(settings)

    @api.get("/api/v1/webhooks", tags=["panel"])
    def webhooks_overview() -> dict[str, Any]:
        """Combined panel feed: subscriptions, delivery summary, recent history."""
        with database.session() as session:
            return webhook_overview(session, settings)

    @api.get("/api/v1/webhooks/subscriptions", tags=["panel"])
    def webhooks_subscriptions() -> dict[str, Any]:
        """All registered webhook subscriptions with delivery counts."""
        with database.session() as session:
            return list_subscriptions(session, settings)

    @api.post("/api/v1/webhooks/subscriptions", tags=["panel"])
    def webhooks_subscription_create(req: SubscriptionRequest) -> dict[str, Any]:
        """Register an outbound webhook endpoint."""
        try:
            with database.session() as session:
                result = create_subscription(
                    session,
                    settings,
                    name=req.name,
                    url=req.url,
                    event_types=req.event_types,
                    secret=req.secret,
                    enabled=req.enabled,
                )
                session.commit()
        except WebhookError as exc:
            raise _http_error(exc) from exc
        return {"status": "created", "subscription": result}

    @api.put("/api/v1/webhooks/subscriptions/{key}", tags=["panel"])
    def webhooks_subscription_update(
        key: str, req: SubscriptionUpdateRequest
    ) -> dict[str, Any]:
        """Partially edit a webhook subscription."""
        try:
            with database.session() as session:
                result = update_subscription(
                    session,
                    settings,
                    key,
                    name=req.name,
                    url=req.url,
                    event_types=req.event_types,
                    secret=req.secret,
                    enabled=req.enabled,
                )
                session.commit()
        except WebhookError as exc:
            raise _http_error(exc) from exc
        return {"status": "updated", "subscription": result}

    @api.delete("/api/v1/webhooks/subscriptions/{key}", tags=["panel"])
    def webhooks_subscription_delete(key: str) -> dict[str, Any]:
        """Remove a subscription (its delivery history is retained)."""
        try:
            with database.session() as session:
                result = delete_subscription(session, settings, key)
                session.commit()
        except WebhookError as exc:
            raise _http_error(exc) from exc
        return {"status": "deleted", **result}

    @api.post("/api/v1/webhooks/dispatch", tags=["panel"])
    def webhooks_dispatch(req: DispatchRequest) -> dict[str, Any]:
        """Fan the newest live-feed events of one kind out to subscribers."""
        try:
            with database.session() as session:
                result = dispatch_event(
                    session,
                    settings,
                    req.event_type,
                    limit=req.limit,
                    simulate_fail_for=req.simulate_fail_for,
                    dry_run=req.dry_run,
                )
                if not req.dry_run:
                    session.commit()
        except WebhookError as exc:
            raise _http_error(exc) from exc
        return {"status": "preview" if req.dry_run else "dispatched", **result}

    @api.post("/api/v1/webhooks/preview", tags=["panel"])
    def webhooks_preview(
        key: str = Query(...), event_type: str = Query(...)
    ) -> dict[str, Any]:
        """Build the signed request envelope a transport would send (no ledger)."""
        try:
            with database.session() as session:
                return build_envelope_preview(session, settings, key, event_type)
        except WebhookError as exc:
            raise _http_error(exc) from exc

    @api.post("/api/v1/webhooks/deliveries/{delivery_key}/attempt", tags=["panel"])
    def webhooks_record_attempt(
        delivery_key: str, req: AttemptRequest
    ) -> dict[str, Any]:
        """Record a transport outcome for one delivery attempt."""
        try:
            with database.session() as session:
                result = record_attempt(
                    session,
                    settings,
                    delivery_key,
                    success=req.success,
                    http_status=req.http_status,
                    error=req.error,
                )
                session.commit()
        except WebhookError as exc:
            raise _http_error(exc) from exc
        return {"status": "recorded", "delivery": result}

    @api.post("/api/v1/webhooks/retry", tags=["panel"])
    def webhooks_retry(
        simulate_fail: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Re-attempt failed deliveries that still have a retry scheduled."""
        with database.session() as session:
            result = retry_due(session, settings, simulate_fail=simulate_fail)
            session.commit()
        return {"status": "retried", **result}

    @api.get("/api/v1/webhooks/deliveries", tags=["panel"])
    def webhooks_deliveries(
        subscription_key: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = Query(default=None, ge=1, le=500),
    ) -> dict[str, Any]:
        """The delivery ledger (newest first), optionally filtered."""
        with database.session() as session:
            return list_deliveries(
                session,
                settings,
                subscription_key=subscription_key,
                status=status,
                limit=limit,
            )
