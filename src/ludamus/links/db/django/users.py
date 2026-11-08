from typing import TYPE_CHECKING

from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.crowd import display_avatar_url as avatar_rule

if TYPE_CHECKING:
    from ludamus.links.db.django.models import User


def display_avatar_url(user: User) -> str:
    return avatar_rule(
        email=user.email, avatar_url=user.avatar_url, use_gravatar=user.use_gravatar
    )


def user_dto(user: User) -> UserDTO:
    return UserDTO.model_validate(user).model_copy(
        update={"avatar_url": display_avatar_url(user)}
    )
