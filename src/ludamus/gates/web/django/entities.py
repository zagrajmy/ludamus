from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from django.http import HttpRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts import (
        AuthenticatedRequestContext,
        DependencyInjectorProtocol,
        RequestContext,
        UserDTO,
    )
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
    def from_user_dto(
        cls, user_dto: UserDTO, *, gravatar_url: Callable[[str], str | None]
    ) -> Self:
        return cls(
            avatar_url=(
                gravatar_url(user_dto.email)
                if user_dto.use_gravatar
                else user_dto.avatar_url or gravatar_url(user_dto.email)
            ),
            discord_username=user_dto.discord_username,
            full_name=user_dto.full_name,
            name=user_dto.name,
            pk=user_dto.pk,
            slug=user_dto.slug,
            username=user_dto.username,
        )


class AuthenticatedRootRequest(HttpRequest):
    context: AuthenticatedRequestContext
    di: DependencyInjectorProtocol
    services: ServicesProtocol


class RootRequest(HttpRequest):
    context: RequestContext
    di: DependencyInjectorProtocol
    services: ServicesProtocol
