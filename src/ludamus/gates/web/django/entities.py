from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from django.http import HttpRequest

from ludamus.pacts.user import display_avatar_url, public_display_name

if TYPE_CHECKING:
    from ludamus.pacts.services import (
        AuthenticatedRequestContext,
        RequestContext,
        ServicesProtocol,
    )
    from ludamus.pacts.user import UserDTO


@dataclass
class UserInfo:
    avatar_url: str | None
    discord_username: str
    full_name: str
    name: str
    pk: int
    slug: str
    username: str

    @classmethod
    def from_user_dto(cls, user_dto: UserDTO) -> Self:
        # Public surfaces never show a raw email — full_name already sanitises
        # via the model, and `name` is forced to the same public label so
        # avatar initials and firstof chains cannot fall through to email.
        public_name = (
            public_display_name(name=user_dto.name, email=user_dto.email)
            or user_dto.full_name
        )
        return cls(
            avatar_url=display_avatar_url(
                email=user_dto.email,
                avatar_url=user_dto.avatar_url,
                use_gravatar=user_dto.use_gravatar,
            )
            or None,
            discord_username=user_dto.discord_username,
            full_name=public_name,
            name=public_name,
            pk=user_dto.pk,
            slug=user_dto.slug,
            username=user_dto.username,
        )

    @classmethod
    def from_public_label(cls, label: str) -> Self:
        """Build a stand-in presenter from a free-text facilitator name."""
        public_name = public_display_name(name=label)
        return cls(
            avatar_url=None,
            discord_username="",
            full_name=public_name,
            name=public_name,
            pk=0,
            slug="",
            username=public_name,
        )


class RootRequest(HttpRequest):
    context: RequestContext
    services: ServicesProtocol


class AuthenticatedRootRequest(RootRequest):
    # Same request, one fact more: a view behind a login gate knows the
    # context carries a user, so anything typed on RootRequest still takes it.
    context: AuthenticatedRequestContext
