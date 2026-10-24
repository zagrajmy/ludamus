"""Stripe's webhooks: one endpoint per signing secret.

`connect/` hears organizers' connected accounts (ticket payments, refunds,
account updates); `billing/` hears Zagrajmy's own account (the yearly plan).
Mounted under `/hooks/`, which private spheres leave open: Stripe has no login,
it signs every delivery instead, and the services refuse what it did not sign.

A 2xx tells Stripe to stop retrying, so only a payload we could not verify is
refused, and only a failed read back from Stripe asks for a retry; an event we
verified but do not act on is still acknowledged.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import View

from ludamus.pacts.payment_api import InvalidWebhookError, PaymentProviderError

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.payment_api import WebhookOutcome

logger = logging.getLogger(__name__)


class _WebhookHandler(Protocol):
    def __call__(self, *, payload: bytes, signature: str) -> WebhookOutcome: ...


def _handle(
    request: RootRequest, *, endpoint: str, handler: _WebhookHandler
) -> JsonResponse:
    try:
        outcome = handler(
            payload=request.body, signature=request.headers.get("Stripe-Signature", "")
        )
    except InvalidWebhookError as exc:
        logger.warning("Stripe %s webhook refused: %s", endpoint, exc)
        return JsonResponse(
            {"error": "Invalid signature or payload."}, status=HTTPStatus.BAD_REQUEST
        )
    except PaymentProviderError as exc:
        logger.warning("Stripe %s webhook deferred: %s", endpoint, exc)
        return JsonResponse(
            {"error": "Stripe could not be reached; retry later."},
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    logger.info("Stripe %s webhook: %s", endpoint, outcome)
    return JsonResponse({"outcome": outcome})


@method_decorator(csrf_exempt, name="dispatch")
class StripeConnectEndpointView(View):
    request: RootRequest
    http_method_names = ("post",)

    @staticmethod
    def post(request: RootRequest) -> JsonResponse:
        return _handle(
            request,
            endpoint="connect",
            handler=request.services.ticket_sales.handle_webhook,
        )


@method_decorator(csrf_exempt, name="dispatch")
class StripeBillingEndpointView(View):
    request: RootRequest
    http_method_names = ("post",)

    @staticmethod
    def post(request: RootRequest) -> JsonResponse:
        return _handle(
            request, endpoint="billing", handler=request.services.plan.handle_webhook
        )
