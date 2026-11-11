"""JSON endpoints the chat calls to start, answer and shape conversations.

Each returns the conversation as its caller now sees it, or nothing, and
answers a refused change with its code: not_found (404) for anything the
caller cannot see, forbidden (403), and the rest as 422.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Concatenate

from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from ludamus.pacts.parley import ParleyConversationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.gates.web.django.parley.views import RootHttpRequest
    from ludamus.pacts.parley import ParleyConversationDTO

logger = logging.getLogger(__name__)

_STATUS = {"not_found": HTTPStatus.NOT_FOUND, "forbidden": HTTPStatus.FORBIDDEN}


class _InvalidBodyError(Exception):
    pass


def _body(request: RootHttpRequest) -> dict[str, object]:
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError as error:
        raise _InvalidBodyError from error
    if not isinstance(body, dict):
        raise _InvalidBodyError
    return body


def _ids(value: object) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(item, int | str) and str(item).isdigit() for item in value
    ):
        raise _InvalidBodyError
    return [int(item) for item in value]


def _id(value: object) -> int:
    return _ids([value])[0]


def _conversation(
    dto: ParleyConversationDTO, status: int = HTTPStatus.OK
) -> JsonResponse:
    return JsonResponse(dto.model_dump(mode="json", by_alias=True), status=status)


def _guarded[**P](
    view: Callable[Concatenate[RootHttpRequest, int, P], HttpResponse],
) -> Callable[Concatenate[RootHttpRequest, P], HttpResponse]:
    """Signed in, a JSON body that parses, and a refusal told as its code."""

    def wrapped(
        request: RootHttpRequest, /, *args: P.args, **kwargs: P.kwargs
    ) -> HttpResponse:
        if (user_id := request.context.current_user_id) is None:
            return JsonResponse(
                {"error": "authentication_required"}, status=HTTPStatus.UNAUTHORIZED
            )
        try:
            return view(request, user_id, *args, **kwargs)
        except _InvalidBodyError:
            return JsonResponse(
                {"error": "invalid"}, status=HTTPStatus.UNPROCESSABLE_ENTITY
            )
        except ParleyConversationError as error:
            return JsonResponse(
                {"error": error.code},
                status=_STATUS.get(error.code, HTTPStatus.UNPROCESSABLE_ENTITY),
            )

    return never_cache(wrapped)


@require_GET
@_guarded
def people(request: RootHttpRequest, user_id: int) -> HttpResponse:
    found = request.services.parley_conversations.search_people(
        user_id=user_id, query=request.GET.get("q", "")
    )
    return JsonResponse(
        {"people": [person.model_dump(mode="json", by_alias=True) for person in found]}
    )


@require_GET
@_guarded
def conversation_list(request: RootHttpRequest, user_id: int) -> HttpResponse:
    found = request.services.parley_conversations.list_for(user_id)
    return JsonResponse(
        {"conversations": [dto.model_dump(mode="json", by_alias=True) for dto in found]}
    )


@require_POST
@_guarded
def start_direct(request: RootHttpRequest, user_id: int) -> HttpResponse:
    recipient_id = _id(_body(request).get("userId"))
    conversation = request.services.parley_conversations.start_direct(
        user_id=user_id, recipient_id=recipient_id
    )
    logger.info(
        "Parley direct conversation started",
        extra={"conversation_id": conversation.id, "user_id": user_id},
    )
    return _conversation(conversation, HTTPStatus.CREATED)


@require_POST
@_guarded
def create_group(request: RootHttpRequest, user_id: int) -> HttpResponse:
    body = _body(request)
    title = body.get("title", "")
    if not isinstance(title, str):
        raise _InvalidBodyError
    conversation = request.services.parley_conversations.create_group(
        user_id=user_id, title=title, member_ids=_ids(body.get("memberIds", []))
    )
    # New, or the one these people already share.
    logger.info(
        "Parley conversation opened with people",
        extra={
            "conversation_id": conversation.id,
            "kind": conversation.kind,
            "members": len(conversation.members),
            "user_id": user_id,
        },
    )
    return _conversation(conversation, HTTPStatus.CREATED)


@require_POST
@_guarded
def accept(request: RootHttpRequest, user_id: int, pk: int) -> HttpResponse:
    conversation = request.services.parley_conversations.accept(
        user_id=user_id, conversation_id=pk
    )
    logger.info(
        "Parley request accepted", extra={"conversation_id": pk, "user_id": user_id}
    )
    return _conversation(conversation)


@require_POST
@_guarded
def decline(request: RootHttpRequest, user_id: int, pk: int) -> HttpResponse:
    request.services.parley_conversations.decline(user_id=user_id, conversation_id=pk)
    logger.info(
        "Parley request declined", extra={"conversation_id": pk, "user_id": user_id}
    )
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


@require_POST
@_guarded
def leave(request: RootHttpRequest, user_id: int, pk: int) -> HttpResponse:
    request.services.parley_conversations.leave(user_id=user_id, conversation_id=pk)
    logger.info(
        "Parley conversation left", extra={"conversation_id": pk, "user_id": user_id}
    )
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


@require_POST
@_guarded
def add_members(request: RootHttpRequest, user_id: int, pk: int) -> HttpResponse:
    conversation = request.services.parley_conversations.add_members(
        user_id=user_id,
        conversation_id=pk,
        member_ids=_ids(_body(request).get("memberIds")),
    )
    logger.info(
        "Parley group members added",
        extra={
            "conversation_id": pk,
            "members": len(conversation.members),
            "user_id": user_id,
        },
    )
    return _conversation(conversation)


@require_POST
@_guarded
def remove_member(
    request: RootHttpRequest, user_id: int, pk: int, member_id: int
) -> HttpResponse:
    request.services.parley_conversations.remove_member(
        user_id=user_id, conversation_id=pk, member_id=member_id
    )
    logger.info(
        "Parley group member removed",
        extra={"conversation_id": pk, "member_id": member_id, "user_id": user_id},
    )
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


@require_POST
@_guarded
def rename(request: RootHttpRequest, user_id: int, pk: int) -> HttpResponse:
    name = _body(request).get("name", "")
    if not isinstance(name, str):
        raise _InvalidBodyError
    conversation = request.services.parley_conversations.rename(
        user_id=user_id, conversation_id=pk, name=name
    )
    logger.info(
        "Parley conversation renamed",
        extra={"conversation_id": pk, "named": bool(name.strip()), "user_id": user_id},
    )
    return _conversation(conversation)


@require_POST
@_guarded
def block(request: RootHttpRequest, user_id: int) -> HttpResponse:
    blocked_id = _id(_body(request).get("userId"))
    request.services.parley_conversations.block(user_id=user_id, blocked_id=blocked_id)
    logger.info("Parley person blocked", extra={"user_id": user_id})
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


@require_POST
@_guarded
def unblock(request: RootHttpRequest, user_id: int, blocked_id: int) -> HttpResponse:
    request.services.parley_conversations.unblock(
        user_id=user_id, blocked_id=blocked_id
    )
    logger.info("Parley person unblocked", extra={"user_id": user_id})
    return HttpResponse(status=HTTPStatus.NO_CONTENT)
