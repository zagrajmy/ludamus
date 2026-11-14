"""Signed-token minting and verification for the MCP endpoints.

Tokens are Django-signed values, no DB table: revocation is flipping the
superuser flag or removing the sphere manager; global rotation is changing
`SECRET_KEY`. Every request re-checks the caller's standing in the database.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core import signing

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.mcp import ActorContext, ToolScope

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest

logger = logging.getLogger(__name__)

SIGNING_SALT = "ludamus.mcp"
TOKEN_MAX_AGE_DAYS = 30


def mint_token(user_id: int) -> str:
    return signing.dumps({"user_id": user_id}, salt=SIGNING_SALT)


def mint_organizer_token(*, user_id: int, sphere_id: int, event_id: int) -> str:
    payload = {
        "user_id": user_id,
        "scope": ToolScope.ORGANIZER.value,
        "sphere_id": sphere_id,
        "event_id": event_id,
    }
    return signing.dumps(payload, salt=SIGNING_SALT)


def _bearer_payload(request: RootRequest) -> dict[str, object] | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        _refuse("no bearer token")
        return None
    try:
        payload = signing.loads(
            header.removeprefix("Bearer "),
            salt=SIGNING_SALT,
            max_age=TOKEN_MAX_AGE_DAYS * 24 * 60 * 60,
        )
    except signing.SignatureExpired:
        _refuse("token expired")
        return None
    except signing.BadSignature:
        _refuse("bad token signature")
        return None
    if not isinstance(payload, dict):
        _refuse("token is not a mapping")
        return None
    return payload


def _refuse(reason: str) -> None:
    # Every refusal is the same 401 to the caller; the log says which one.
    logger.info("MCP token refused: %s", reason)


def authenticate_maintainer(request: RootRequest) -> ActorContext | None:
    if (payload := _bearer_payload(request)) is None:
        return None
    # Pre-#483 maintainer tokens carry no scope field; treat both shapes alike.
    if payload.get("scope") not in {None, ToolScope.MAINTAINER.value}:
        _refuse("not a maintainer token")
        return None
    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        _refuse("maintainer token without a user id")
        return None
    user_model = get_user_model()
    is_superuser = user_model.objects.filter(
        pk=user_id, is_active=True, is_superuser=True
    ).exists()
    if not is_superuser:
        _refuse(f"user {user_id} is no longer an active superuser")
        return None
    return ActorContext(user_id=user_id, scope=ToolScope.MAINTAINER)


def authenticate_organizer(request: RootRequest) -> ActorContext | None:
    if (payload := _bearer_payload(request)) is None:
        return None
    if payload.get("scope") != ToolScope.ORGANIZER.value:
        _refuse("not an organizer token")
        return None
    user_id = payload.get("user_id")
    sphere_id = payload.get("sphere_id")
    event_id = payload.get("event_id")
    if (
        not isinstance(user_id, int)
        or not isinstance(sphere_id, int)
        or not isinstance(event_id, int)
    ):
        _refuse("organizer token without user, sphere or event id")
        return None
    user_model = get_user_model()
    slug = (
        user_model.objects.filter(pk=user_id, is_active=True)
        .values_list("slug", flat=True)
        .first()
    )
    if slug is None:
        _refuse(f"user {user_id} is gone or inactive")
        return None
    if not request.services.sphere_panel.can_write_programme(sphere_id, slug):
        _refuse(f"user {user_id} may not write sphere {sphere_id}")
        return None
    try:
        request.services.events.require_in_sphere(
            sphere_id=sphere_id, event_id=event_id
        )
    except NotFoundError:
        _refuse(f"event {event_id} is not in sphere {sphere_id}")
        return None
    return ActorContext(
        user_id=user_id,
        scope=ToolScope.ORGANIZER,
        sphere_id=sphere_id,
        event_id=event_id,
    )
