from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from uuid import UUID

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import EventDTO
from ludamus.pacts.proposal_categories import ProposalCategoryDTO
from ludamus.pacts.sessions import SessionDTO, SessionStatus
from ludamus.pacts.tracks import TrackDTO
from ludamus.pacts.user import AgeBand, UserDTO, UserType

DEFAULT_JOINED = datetime(2024, 1, 1, tzinfo=UTC)
DEFAULT_START = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
DEFAULT_END = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


class FakeUsers:
    """Users by slug and by pk; a miss raises NotFoundError, as the repo does."""

    def __init__(self, *users: UserDTO) -> None:
        self.users = {user.slug: user for user in users}

    def read(self, slug: str) -> UserDTO:
        try:
            return self.users[slug]
        except KeyError:
            raise NotFoundError from None

    def read_by_id(self, pk: int) -> UserDTO:
        for user in self.users.values():
            if user.pk == pk:
                return user
        raise NotFoundError

    def read_by_ids(self, pks) -> list[UserDTO]:
        by_pk = {user.pk: user for user in self.users.values()}
        return [by_pk[pk] for pk in pks if pk in by_pk]

    def read_by_email(self, email: str) -> UserDTO:
        for user in self.users.values():
            if user.email == email:
                return user
        raise NotFoundError

    def update(self, user_slug: str, user_data) -> None:
        self.users[user_slug] = self.users[user_slug].model_copy(update=dict(user_data))


class FakeTransaction:
    @staticmethod
    def atomic() -> AbstractContextManager[None]:
        return nullcontext()

    @staticmethod
    def savepoint() -> AbstractContextManager[None]:
        return nullcontext()


def user_dto(**overrides) -> UserDTO:
    defaults = {
        "age_band": AgeBand.UNKNOWN,
        "privacy_revision": UUID(int=1),
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
        "contact_language": "",
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
