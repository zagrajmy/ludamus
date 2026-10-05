"""Calendar replies to encounter invites, forwarded by the Email Worker.

A guest's calendar answers an invite by mailing an iTIP REPLY to the
invite's organizer address. Cloudflare Email Routing hands that mail to the
Worker in ``cloudflare/encounter-replies``, which posts it here raw. Mounted
under ``/hooks/``, which private spheres leave open: the Worker has no login.
"""

from __future__ import annotations

import email
import email.policy
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
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
        try:
            raw = request.body
        except RequestDataTooBig:
            logger.info("Calendar reply webhook: message over the upload limit")
            return JsonResponse(
                {"error": "Message too large."}, status=HTTPStatus.UNPROCESSABLE_ENTITY
            )
        reply = _calendar_reply(raw)
        if reply is None or not address:
            logger.info("Calendar reply webhook: no iTIP REPLY in the message")
            return JsonResponse(
                {"error": "Not a calendar reply."},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        outcome = request.services.encounter_replies.apply_calendar_reply(
            address=address, reply=reply
        )
        if outcome is ReplyOutcome.FORGED:
            # NOTE: domains only; a mismatch is mostly a client answering from
            # an alias (googlemail.com for gmail.com), which the domains show.
            logger.warning(
                "Calendar reply %s: token does not match (attendee @%s, to @%s)",
                reply.uid,
                reply.attendee_email.rpartition("@")[2],
                address.rpartition("@")[2],
            )
            return JsonResponse({"outcome": outcome}, status=HTTPStatus.FORBIDDEN)
        logger.info("Calendar reply %s: %s", reply.uid, outcome)
        return JsonResponse({"outcome": outcome})


def _calendar_reply(raw: bytes) -> CalendarReply | None:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    for part in message.walk():
        if part.get_content_type() not in _CALENDAR_TYPES:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        try:
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except LookupError:
            text = payload.decode("utf-8", "replace")
        if reply := parse_reply(text):
            return reply
    return None
