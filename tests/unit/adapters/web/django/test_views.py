from datetime import UTC, datetime

from ludamus.gates.web.django.entities import UserInfo
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.crowd import UserDTO, UserType


def _make_user_dto(**overrides) -> UserDTO:
    defaults = {
        "avatar_url": "https://example.com/old.png",
        "date_joined": datetime(2024, 1, 1, tzinfo=UTC),
        "discord_username": "",
        "email": "old@example.com",
        "full_name": "Old Name",
        "is_active": True,
        "is_authenticated": True,
        "is_staff": False,
        "is_superuser": False,
        "name": "Old Name",
        "pk": 1,
        "slug": "old-slug",
        "use_gravatar": False,
        "user_type": UserType.ACTIVE,
        "username": "auth0|abc",
    }
    return UserDTO(**(defaults | overrides))


class TestUserInfoFromUserDto:
    def test_uses_auth0_avatar_by_default(self):
        dto = _make_user_dto(
            avatar_url="https://example.com/auth0.png", use_gravatar=False
        )
        info = UserInfo.from_user_dto(dto, gravatar_url=gravatar_url)
        assert info.avatar_url == "https://example.com/auth0.png"

    def test_uses_gravatar_when_use_gravatar_is_true(self):
        dto = _make_user_dto(
            avatar_url="https://example.com/auth0.png",
            use_gravatar=True,
            email="test@example.com",
        )
        info = UserInfo.from_user_dto(dto, gravatar_url=gravatar_url)
        assert info.avatar_url == gravatar_url("test@example.com")

    def test_falls_back_to_gravatar_when_no_auth0_avatar(self):
        dto = _make_user_dto(
            avatar_url="", use_gravatar=False, email="test@example.com"
        )
        info = UserInfo.from_user_dto(dto, gravatar_url=gravatar_url)
        assert info.avatar_url == gravatar_url("test@example.com")

    def test_returns_none_when_no_avatar_and_no_email(self):
        dto = _make_user_dto(avatar_url="", use_gravatar=False, email="")
        info = UserInfo.from_user_dto(dto, gravatar_url=gravatar_url)
        assert info.avatar_url is None
