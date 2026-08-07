from datetime import UTC, datetime

from ludamus.pacts import (
    OrganizerFieldDTO,
    OrganizerFieldOptionDTO,
    ProposalCategoryDTO,
)
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


RPG_OPTION = OrganizerFieldOptionDTO(label="RPG", order=1, pk=1, value="rpg")
BOARD_OPTION = OrganizerFieldOptionDTO(label="Board", order=0, pk=2, value="board")


def organizer_field_dto(**overrides) -> OrganizerFieldDTO:
    defaults = {
        "field_type": "select",
        "name": "Tags",
        "options": [RPG_OPTION, BOARD_OPTION],
        "order": 0,
        "pk": 1,
        "question": "What tags apply?",
        "slug": "tags",
    }
    return OrganizerFieldDTO(**(defaults | overrides))


def category(
    *,
    pk=1,
    name="Talk",
    slug="talk",
    min_participants_limit=0,
    max_participants_limit=0,
    durations=(),
):
    return ProposalCategoryDTO(
        description="",
        durations=list(durations),
        end_time=None,
        max_participants_limit=max_participants_limit,
        min_participants_limit=min_participants_limit,
        name=name,
        pk=pk,
        slug=slug,
        start_time=None,
    )
