from typing import TYPE_CHECKING

from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.crowd import UserDTO

if TYPE_CHECKING:
    from ludamus.links.db.django.models import User


def display_avatar_url(user: User) -> str:
    if user.use_gravatar:
        return gravatar_url(user.email) or ""
    return user.avatar_url or gravatar_url(user.email) or ""


def user_dto(user: User) -> UserDTO:
    return UserDTO.model_validate(user).model_copy(
        update={"avatar_url": display_avatar_url(user)}
    )
