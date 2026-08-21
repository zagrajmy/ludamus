from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from pydantic import ValidationError

from ludamus.pacts.parley import ParleyReportData

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ludamus.pacts.legacy import RequestContext
    from ludamus.pacts.services import ServicesProtocol

    class RootHttpRequest(HttpRequest):
        context: RequestContext
        services: ServicesProtocol


logger = logging.getLogger(__name__)


def _copy() -> dict[str, str]:
    return {
        "title": _("Parley"),
        "closeLabel": _("Close Parley"),
        "loading": _("Gathering conversations…"),
        "offline": _("Parley lost the thread. Reconnecting…"),
        "emptySphere": _(
            "Quiet in here. Say hello before someone starts a rules debate."
        ),
        "emptySession": _("You found the table first. Leave a note for the others."),
        "readOnly": _("This parley has ended, but you can still read what was said."),
        "presence": _("people around"),
        "messageLabel": _("Message"),
        "sendLabel": _("Send message"),
        "roomsLabel": _("Conversations"),
        "backLabel": _("Back to conversations"),
        "loadEarlier": _("Load earlier messages"),
        "deletedMessage": _("Message deleted"),
        "retry": _("Try again"),
        "sending": _("Sending…"),
        "writePlaceholder": _("Write a message…"),
        "connectionError": _("Could not connect to Parley."),
        "messageTooLong": _("Messages can be up to 1,000 characters."),
        "errorArchived": _("This conversation is archived."),
        "errorExpired": _("Your Parley access expired. Reopen Parley to continue."),
        "errorForbidden": _("You do not have permission to do that."),
        "errorInvalid": _("That message could not be sent."),
        "errorMuted": _("Your writing access is currently muted."),
        "errorRateLimited": _("Too many messages. Wait a moment and try again."),
        "errorUnknown": _("Something went wrong. Try again."),
        "deleteLabel": _("Delete message"),
        "online": _("online"),
        "sessionRoom": _("Programme point"),
        "sphereRoom": _("Common room"),
        "moderatorDelete": _("Delete as moderator"),
        "muteOneHour": _("Mute for 1 hour"),
        "muteOneDay": _("Mute for 24 hours"),
        "muteSevenDays": _("Mute for 7 days"),
        "muteIndefinitely": _("Mute indefinitely"),
        "muteLabel": _("Change writing access"),
        "restoreWriting": _("Restore writing access"),
        "unread": _("Unread"),
        "copyLink": _("Copy message link"),
        "reportMessage": _("Report message"),
        "reported": _("Message reported."),
    }


@never_cache
@require_GET
def bootstrap(request: RootHttpRequest) -> JsonResponse:
    if request.context.current_user_id is None:
        return JsonResponse({"error": "authentication_required"}, status=401)

    payload = request.services.parley.bootstrap(
        sphere_id=request.context.current_sphere_id,
        user_id=request.context.current_user_id,
        now=datetime.now(tz=UTC),
    )
    if payload is None:
        return JsonResponse({"error": "parley_unavailable"}, status=404)
    response_data = payload.model_dump(mode="json", by_alias=True)
    response_data["copy"] = _copy()
    response_data["csrfToken"] = get_token(request)
    return JsonResponse(response_data)


@never_cache
@require_POST
def report(request: RootHttpRequest) -> JsonResponse:
    if request.context.current_user_id is None:
        return JsonResponse({"error": "authentication_required"}, status=401)
    try:
        data = ParleyReportData(
            sphere_id=request.context.current_sphere_id,
            user_id=request.context.current_user_id,
            room_id=request.POST["room_id"],
            message_id=int(request.POST["message_id"]),
            reason=request.POST.get("reason", ""),
        )
    except KeyError, ValidationError, ValueError:
        return JsonResponse({"error": "invalid_report"}, status=422)
    created = request.services.parley.report_message(
        data=data, now=datetime.now(tz=UTC)
    )
    if not created:
        return JsonResponse({"error": "invalid_report"}, status=422)
    logger.info(
        "Parley message reported",
        extra={
            "message_id": data.message_id,
            "room_id": data.room_id,
            "sphere_id": data.sphere_id,
            "user_id": data.user_id,
        },
    )
    return JsonResponse({}, status=201)
