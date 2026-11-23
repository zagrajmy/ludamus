from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from uuid import UUID

from ludamus.pacts.enrollment import (
    PromotionMode,
    PromotionStateDTO,
    SessionSeatsDTO,
    WaitingParticipantDTO,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import EventDTO, FacilitatorListItemDTO
from ludamus.pacts.facilitators import FacilitatorChangeLogDTO, FacilitatorDTO
from ludamus.pacts.fields import OrganizerFieldDTO, SessionFieldValueDTO
from ludamus.pacts.guild import GuildSummaryDTO
from ludamus.pacts.integrations import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
)
from ludamus.pacts.panel import EventPanelSettingsDTO
from ludamus.pacts.proposal_categories import ProposalCategoryDTO
from ludamus.pacts.propose import AccreditationType
from ludamus.pacts.sessions import SessionDTO, SessionListItemDTO, SessionStatus
from ludamus.pacts.sphere import SiteDTO, SphereDTO
from ludamus.pacts.timetable import AgendaItemDTO
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
    def durable() -> AbstractContextManager[None]:
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


def sphere_dto(**overrides) -> SphereDTO:
    defaults = {
        "name": "Sphere",
        "pk": 1,
        "site": SiteDTO(domain="example.com", name="Example", pk=1),
    }
    return SphereDTO(**(defaults | overrides))


def agenda_item_dto(**overrides) -> AgendaItemDTO:
    defaults = {
        "end_time": DEFAULT_START + timedelta(hours=1),
        "pk": 1,
        "schedule_confirmed": False,
        "session_id": 1,
        "session_title": "Session",
        "space_id": 1,
        "start_time": DEFAULT_START,
    }
    return AgendaItemDTO(**(defaults | overrides))


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


def session_list_item_dto(**overrides) -> SessionListItemDTO:
    defaults = {
        "category_name": "",
        "creation_time": DEFAULT_START,
        "facilitator_name": "",
        "is_scheduled": False,
        "pk": 1,
        "status": SessionStatus.ACCEPTED,
        "title": "Session",
    }
    return SessionListItemDTO(**(defaults | overrides))


def event_integration_dto(**overrides) -> EventIntegrationDTO:
    defaults = {
        "config_json": "{}",
        "connection_display_name": "Connection",
        "connection_id": 1,
        "display_name": "Integration",
        "event_id": 1,
        "implementation": IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER,
        "kind": IntegrationKind.IMPORT,
        "pk": 1,
        "settings_json": "{}",
    }
    return EventIntegrationDTO(**(defaults | overrides))


def facilitator_dto(**overrides) -> FacilitatorDTO:
    defaults = {
        "accreditation_type": AccreditationType.NONE,
        "display_name": "Facilitator",
        "event_id": 1,
        "pk": 1,
        "slug": "facilitator",
        "user_id": None,
    }
    return FacilitatorDTO(**(defaults | overrides))


def facilitator_list_item_dto(**overrides) -> FacilitatorListItemDTO:
    defaults = {
        "accreditation_type": AccreditationType.NONE,
        "display_name": "Facilitator",
        "organizer_id": None,
        "organizer_name": None,
        "pk": 1,
        "session_count": 0,
        "slug": "facilitator",
        "user_id": None,
    }
    return FacilitatorListItemDTO(**(defaults | overrides))


def facilitator_change_log_dto(**overrides) -> FacilitatorChangeLogDTO:
    defaults = {
        "changes": [],
        "creation_time": DEFAULT_START,
        "event_id": 1,
        "facilitator_id": 1,
        "facilitator_name": "Facilitator",
        "pk": 1,
        "user_id": None,
        "user_name": "",
    }
    return FacilitatorChangeLogDTO(**(defaults | overrides))


def event_panel_settings_dto(**overrides) -> EventPanelSettingsDTO:
    return EventPanelSettingsDTO(**({"pk": 1} | overrides))


def guild_summary_dto(**overrides) -> GuildSummaryDTO:
    defaults = {"name": "Guild", "pk": 1, "slug": "guild"}
    return GuildSummaryDTO(**(defaults | overrides))


def organizer_field_dto(**overrides) -> OrganizerFieldDTO:
    defaults = {
        "field_type": "text",
        "name": "Field",
        "order": 0,
        "pk": 1,
        "question": "Field?",
        "slug": "field",
    }
    return OrganizerFieldDTO(**(defaults | overrides))


def session_field_value_dto(**overrides) -> SessionFieldValueDTO:
    defaults = {"field_name": "Field", "field_question": "Field?", "value": ""}
    return SessionFieldValueDTO(**(defaults | overrides))


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


def promotion_state(
    waiting: list[WaitingParticipantDTO], *, seats: int = 1
) -> PromotionStateDTO:
    """Build the state of an auto-promoting session a week out that nobody hosts."""
    return PromotionStateDTO(
        session_id=1,
        session_title="S",
        event_slug="ev",
        start_time=datetime(2026, 6, 4, 12, 0, tzinfo=UTC) + timedelta(days=7),
        promotion_mode=PromotionMode.AUTO,
        offer_claim_window=timedelta(hours=24),
        host_ids=frozenset(),
        seats=SessionSeatsDTO(
            participants_limit=seats, seating_percentage=None, enrolled_count=0
        ),
        waiting=waiting,
    )
