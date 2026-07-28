"""Signed-token minting and verification for the MCP endpoints.

Tokens are Django-signed values, no DB table: revocation is flipping the
superuser flag or removing the sphere manager; global rotation is changing
`SECRET_KEY`. Every request re-checks the caller's standing in the database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core import signing

from ludamus.pacts.mcp import ActorContext, ToolScope

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest

SIGNING_SALT = "ludamus.mcp"
TOKEN_MAX_AGE_DAYS = 30


def mint_token(user_id: int) -> str:
    return signing.dumps({"user_id": user_id}, salt=SIGNING_SALT)


def mint_organizer_token(*, user_id: int, sphere_id: int) -> str:
    payload = {
        "user_id": user_id,
        "scope": ToolScope.ORGANIZER.value,
        "sphere_id": sphere_id,
    }
    return signing.dumps(payload, salt=SIGNING_SALT)


def _bearer_payload(request: RootRequest) -> dict[str, object] | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        payload = signing.loads(
            header.removeprefix("Bearer "),
            salt=SIGNING_SALT,
            max_age=TOKEN_MAX_AGE_DAYS * 24 * 60 * 60,
        )
    except signing.BadSignature:
        return None
    return payload if isinstance(payload, dict) else None


def authenticate_maintainer(request: RootRequest) -> ActorContext | None:
    if (payload := _bearer_payload(request)) is None:
        return None
    # Pre-#483 maintainer tokens carry no scope field; treat both shapes alike.
    if payload.get("scope") not in {None, ToolScope.MAINTAINER.value}:
        return None
    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        return None
    user_model = get_user_model()
    is_superuser = user_model.objects.filter(
        pk=user_id, is_active=True, is_superuser=True
    ).exists()
    if not is_superuser:
        return None
    return ActorContext(user_id=user_id, scope=ToolScope.MAINTAINER)


def authenticate_organizer(request: RootRequest) -> ActorContext | None:
    payload = _bearer_payload(request)
    if payload is None or payload.get("scope") != ToolScope.ORGANIZER.value:
        return None
    user_id = payload.get("user_id")
    sphere_id = payload.get("sphere_id")
    if not isinstance(user_id, int) or not isinstance(sphere_id, int):
        return None
    user_model = get_user_model()
    row = (
        user_model.objects.filter(pk=user_id, is_active=True)
        .values_list("slug", "is_superuser")
        .first()
    )
    if row is None:
        return None
    slug, is_superuser = row
    if not is_superuser and not request.services.sphere_panel.is_manager(
        sphere_id, slug
    ):
        return None
    return ActorContext(user_id=user_id, scope=ToolScope.ORGANIZER, sphere_id=sphere_id)
