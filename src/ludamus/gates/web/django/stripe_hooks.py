"""Stripe's webhooks: one endpoint per signing secret.

`connect/` hears organizers' connected accounts (ticket payments, refunds,
account updates); `billing/` hears Zagrajmy's own account (the yearly plan).
Mounted under `/hooks/`, which private spheres leave open: Stripe has no login,
it signs every delivery instead, and the services refuse what it did not sign.

A 2xx tells Stripe to stop retrying, so only a payload we could not verify is
refused; an event we verified but do not act on is still acknowledged.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import View

from ludamus.pacts.payment_api import InvalidWebhookError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.gates.web.django.entities import RootRequest

logger = logging.getLogger(__name__)


def _handle(
    request: RootRequest, *, endpoint: str, handler: Callable[..., str]
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
