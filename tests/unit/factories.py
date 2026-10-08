from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime

from ludamus.pacts import (
    EventDTO,
    ProposalCategoryDTO,
    SessionDTO,
    SessionStatus,
    TrackDTO,
)
from ludamus.pacts.crowd import UserDTO, UserType

DEFAULT_JOINED = datetime(2024, 1, 1, tzinfo=UTC)
DEFAULT_START = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
DEFAULT_END = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


class FakeTransaction:
    @staticmethod
    def atomic() -> AbstractContextManager[None]:
        return nullcontext()

    @staticmethod
    def savepoint() -> AbstractContextManager[None]:
        return nullcontext()


def user_dto(**overrides) -> UserDTO:
    defaults = {
        "avatar_url": "",
        "date_joined": DEFAULT_JOINED,
        "discord_username": "",
        "email": "",
        "email_verified": False,
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


def event_dto(**overrides) -> EventDTO:
    defaults = {
        "description": "",
        "end_time": DEFAULT_END,
        "name": "Konwent",
        "pk": 1,
        "proposal_end_time": None,
        "proposal_start_time": None,
        "publication_time": None,
        "slug": "konwent",
        "sphere_id": 1,
        "start_time": DEFAULT_START,
    }
    return EventDTO(**(defaults | overrides))


def session_dto(**overrides) -> SessionDTO:
    defaults = {
        "category_id": None,
        "contact_email": "",
        "creation_time": DEFAULT_START,
        "description": "",
        "facilitator_name": "",
        "min_age": 0,
        "modification_time": DEFAULT_START,
        "participants_limit": 0,
        "pk": 1,
        "presenter_id": None,
        "slug": "s",
        "status": SessionStatus.ACCEPTED,
        "title": "Session",
    }
    return SessionDTO(**(defaults | overrides))


def track_dto(**overrides) -> TrackDTO:
    defaults = {
        "creation_time": DEFAULT_START,
        "event_id": 1,
        "is_public": True,
        "modification_time": DEFAULT_START,
        "name": "Track",
        "pk": 1,
        "slug": "track",
    }
    return TrackDTO(**(defaults | overrides))


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
