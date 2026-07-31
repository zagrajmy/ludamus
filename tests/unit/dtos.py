"""Shared DTO builders for unit tests."""

from datetime import UTC, datetime

from ludamus.pacts.crowd import UserDTO, UserType

DEFAULT_JOINED = datetime(2024, 1, 1, tzinfo=UTC)


def user_dto(**overrides) -> UserDTO:
    defaults = {
        "avatar_url": "",
        "date_joined": DEFAULT_JOINED,
        "discord_username": "",
        "email": "",
        "full_name": "",
        "is_active": True,
        "is_authenticated": True,
        "is_staff": False,
        "is_superuser": False,
        "name": "",
        "pk": 1,
        "slug": "manager",
        "use_gravatar": False,
        "user_type": UserType.ACTIVE,
        "username": "auth0|sub",
    }
    return UserDTO(**(defaults | overrides))
