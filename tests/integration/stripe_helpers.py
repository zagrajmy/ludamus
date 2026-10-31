"""Stripe stand-ins for integration tests: settings, signed webhooks, HTTP mocks.

Also the ticket rows and pages they act on. Nothing here fakes our own code.
Stripe's API is answered at the HTTP layer with `responses`, and webhooks are
signed the way Stripe signs them, so the real adapter, services, repositories
and views all run.
"""

import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

from django.urls import reverse

from ludamus.links.db.django.models import (
    PayoutAccount,
    TicketOrder,
    TicketOrderLine,
    TicketType,
)
from ludamus.pacts.tickets import OrderStatus

API = "https://api.stripe.com/v1"
CONNECT_SECRET = "whsec_connect_test"
BILLING_SECRET = "whsec_billing_test"
ACCOUNT_ID = "acct_test_organizer"
# Stands in for a guest's keyed network, the way the buy view stores one.
GUEST_CLIENT = "9" * 64


def signed(payload: dict, secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return body, f"t={timestamp},v1={digest}"


def event_payload(
    event_type: str, obj: dict, *, event_id: str = "evt_1", account: str | None = None
) -> dict:
    payload: dict = {
        "id": event_id,
        "object": "event",
        "type": event_type,
        "data": {"object": obj},
    }
    if account is not None:
        payload["account"] = account
    return payload


def post_hook(client, url: str, payload: dict, secret: str):
    body, signature = signed(payload, secret)
    return client.post(
        url,
        data=body,
        content_type="application/json",
        headers={"Stripe-Signature": signature},
    )


def connected_account(sphere, *, charges_enabled: bool = True) -> PayoutAccount:
    return PayoutAccount.objects.create(
        sphere=sphere,
        stripe_account_id=ACCOUNT_ID,
        details_submitted=charges_enabled,
        charges_enabled=charges_enabled,
        payouts_enabled=charges_enabled,
    )


def ticket_type(event, **fields) -> TicketType:
    defaults: dict = {"name": "Weekend pass", "price": 5000}
    return TicketType.objects.create(event=event, **(defaults | fields))


def order(
    event,
    *,
    buyer,
    lines: list[tuple[TicketType, int]],
    status: OrderStatus = OrderStatus.PENDING,
    session_id: str = "cs_test_1",
    payment_intent_id: str = "",
    hold_minutes: int = 30,
    email: str | None = None,
    guest_client: str = "",
) -> TicketOrder:
    # `buyer=None` is a guest's order: its reference is all that finds it.
    total = sum(kind.price * quantity for kind, quantity in lines)
    created = TicketOrder.objects.create(
        event=event,
        buyer=buyer,
        reference=secrets.token_urlsafe(16),
        email=(buyer.email if buyer is not None else "") if email is None else email,
        guest_client=guest_client,
        status=status,
        currency="pln",
        total=total,
        platform_fee=(total * 350 + 5000) // 10_000,
        stripe_account_id=ACCOUNT_ID,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=payment_intent_id,
        hold_until=datetime.now(UTC) + timedelta(minutes=hold_minutes),
    )
    for kind, quantity in lines:
        TicketOrderLine.objects.create(
            order=created, ticket_type=kind, quantity=quantity, unit_price=kind.price
        )
    return created


def tickets_url(event) -> str:
    return reverse("web:event:event-tickets", kwargs={"event_slug": event.slug})


def order_url(event, placed: TicketOrder) -> str:
    # `event` may be another than the order's: its reference tried elsewhere.
    return reverse(
        "web:event:event-ticket-order",
        kwargs={"event_slug": event.slug, "reference": placed.reference},
    )


def cancel_url(event, placed: TicketOrder) -> str:
    return reverse(
        "web:event:event-ticket-order-cancel",
        kwargs={"event_slug": event.slug, "reference": placed.reference},
    )
