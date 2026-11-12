"""Email about chat mentions: the Worker's report of unread ones, and opting out."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic.base import View
from pydantic import BaseModel, StrictStr, ValidationError

from ludamus.pacts.parley_mentions import (
    ParleyMentionClaimsError,
    ParleyMentionDeliveryStatus,
    ParleyMentionsOffError,
    ParleyMentionTokenError,
)

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.parley_mentions import ParleyMentionUnsubscribePayload

logger = logging.getLogger(__name__)


class _Report(BaseModel):
    token: StrictStr


def _token(request: RootRequest) -> str | None:
    try:
        return _Report.model_validate_json(request.body).token
    except ValidationError:
        return None


# NOTE: the Worker posts here; its signature, not a session, vouches for it.
@csrf_exempt
@require_POST
def unread(request: RootRequest) -> HttpResponse:
    if (token := _token(request)) is None:
        return JsonResponse({"error": "invalid"}, status=HTTPStatus.BAD_REQUEST)
    try:
        delivery = request.services.parley_mentions.deliver(
            token=token, now=datetime.now(tz=UTC)
        )
    except ParleyMentionsOffError:
        return JsonResponse(
            {"error": "unavailable"}, status=HTTPStatus.SERVICE_UNAVAILABLE
        )
    except ParleyMentionTokenError:
        logger.warning("Parley mention report refused: bad token")
        return JsonResponse({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
    except ParleyMentionClaimsError:
        logger.warning("Parley mention report refused: malformed claims")
        return JsonResponse({"error": "invalid"}, status=HTTPStatus.BAD_REQUEST)
    if delivery.status == ParleyMentionDeliveryStatus.THROTTLED:
        return JsonResponse(
            {"retryAfter": delivery.retry_after}, status=HTTPStatus.TOO_MANY_REQUESTS
        )
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


def _unsubscribe_page(
    request: RootRequest,
    *,
    token: str,
    payload: ParleyMentionUnsubscribePayload | None,
    done: bool = False,
) -> TemplateResponse:
    return TemplateResponse(
        request,
        "parley/mention_unsubscribe.html",
        {"payload": payload, "token": token, "done": done},
        status=HTTPStatus.OK if payload else HTTPStatus.NOT_FOUND,
    )


class UnsubscribePageView(View):
    """Confirm stopping mention emails, straight from one.

    GET changes nothing: mail scanners prefetch links, so only the button (or
    a mail client's one-click POST) turns them off.
    """

    @staticmethod
    def get(request: RootRequest, token: str) -> HttpResponse:
        payload = request.services.parley_mentions.read_unsubscribe_token(token)
        return _unsubscribe_page(request, token=token, payload=payload)


# NOTE: RFC 8058 one-click POSTs carry no CSRF token; the signed URL vouches.
@method_decorator(csrf_exempt, name="dispatch")
class UnsubscribeActionView(View):
    @staticmethod
    def get(_request: RootRequest, token: str) -> HttpResponse:
        return redirect(reverse("parley_mention_unsubscribe", kwargs={"token": token}))

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        if request.POST.get("List-Unsubscribe") != "One-Click":
            return redirect(
                reverse("parley_mention_unsubscribe", kwargs={"token": token})
            )
        payload = request.services.parley_mentions.unsubscribe_by_token(token)
        if payload is None:
            logger.warning("Mention mail unsubscribe refused: bad token")
        else:
            logger.info("Mention mail turned off by link: user=%s", payload.user_id)
        return _unsubscribe_page(request, token=token, payload=payload, done=True)
