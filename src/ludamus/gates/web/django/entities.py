from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from django.http import HttpRequest

from ludamus.pacts.crowd import display_avatar_url

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.legacy import AuthenticatedRequestContext, RequestContext
    from ludamus.pacts.services import ServicesProtocol


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
        return cls(
            avatar_url=display_avatar_url(
                email=user_dto.email,
                avatar_url=user_dto.avatar_url,
                use_gravatar=user_dto.use_gravatar,
            )
            or None,
            discord_username=user_dto.discord_username,
            full_name=user_dto.full_name,
            name=user_dto.name,
            pk=user_dto.pk,
            slug=user_dto.slug,
            username=user_dto.username,
        )


class RootRequest(HttpRequest):
    context: RequestContext
    services: ServicesProtocol


class AuthenticatedRootRequest(RootRequest):
    # Same request, one fact more: a view behind a login gate knows the
    # context carries a user, so anything typed on RootRequest still takes it.
    context: AuthenticatedRequestContext
