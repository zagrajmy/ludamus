"""Calendar replies to encounter invites, forwarded by the Email Worker.

A guest's calendar answers an invite by mailing an iTIP REPLY to the
invite's organizer address. Cloudflare Email Routing hands that mail to the
Worker in ``cloudflare/encounter-replies``, which posts it here raw.
"""

from __future__ import annotations

import email
import email.policy
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import View

from ludamus.pacts.calendar import parse_reply
from ludamus.pacts.encounter import ReplyOutcome

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.calendar import CalendarReply


logger = logging.getLogger(__name__)

_CALENDAR_TYPES = frozenset({"text/calendar", "application/ics"})
_STATUS = {
    ReplyOutcome.FORGED: HTTPStatus.FORBIDDEN,
    ReplyOutcome.UNKNOWN: HTTPStatus.NOT_FOUND,
}


@method_decorator(csrf_exempt, name="dispatch")
class EncounterCalendarReplyView(View):
    """Bearer-secret webhook; CSRF does not apply (no cookie auth).

    The body is the raw RFC 5322 message; ``X-Envelope-To`` is the address
    it was delivered to, which carries the per-guest token.
    """

    request: RootRequest

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        if not (secret := settings.ENCOUNTER_REPLY_WEBHOOK_SECRET):
            raise Http404
        if not constant_time_compare(
            request.headers.get("Authorization", ""), f"Bearer {secret}"
        ):
            return HttpResponse(status=HTTPStatus.UNAUTHORIZED)
        address = request.headers.get("X-Envelope-To", "")
        reply = _calendar_reply(request.body)
        if reply is None or not address:
            logger.info("Calendar reply webhook: no iTIP REPLY in the message")
            return JsonResponse(
                {"error": "Not a calendar reply."},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        outcome = request.services.encounter_replies.apply_calendar_reply(
            address=address, reply=reply
        )
        logger.info("Calendar reply %s: %s", reply.uid, outcome)
        return JsonResponse(
            {"outcome": outcome}, status=_STATUS.get(outcome, HTTPStatus.OK)
        )


def _calendar_reply(raw: bytes) -> CalendarReply | None:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    for part in message.walk():
        if part.get_content_type() in _CALENDAR_TYPES:
            content = part.get_content()
            text = content.decode() if isinstance(content, bytes) else str(content)
            if reply := parse_reply(text):
                return reply
    return None
