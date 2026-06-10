from functools import cached_property

from ludamus.links.db.django import repositories
from ludamus.links.db.django.agenda_item import AgendaItemRepository
from ludamus.links.db.django.content_change_log import ContentChangeLogRepository


class Repositories:
    """Lazy flat repository registry.

    Internal to inits — never imported from gates. Mills services receive
    specific repo protocols from this tree, not the tree itself. Buckets
    will appear when the leaf count grows past ~12.
    """

    @cached_property
    def personal_data_fields(self) -> repositories.PersonalDataFieldRepository:
        return repositories.PersonalDataFieldRepository()

    @cached_property
    def proposal_categories(self) -> repositories.ProposalCategoryRepository:
        return repositories.ProposalCategoryRepository()

    @cached_property
    def connections(self) -> repositories.ConnectionsRepository:
        return repositories.ConnectionsRepository()

    @cached_property
    def event_integrations(self) -> repositories.EventIntegrationsRepository:
        return repositories.EventIntegrationsRepository()

    @cached_property
    def spheres(self) -> repositories.SphereRepository:
        return repositories.SphereRepository()

    @cached_property
    def events(self) -> repositories.EventRepository:
        return repositories.EventRepository()

    @cached_property
    def sessions(self) -> repositories.SessionRepository:
        return repositories.SessionRepository()

    @cached_property
    def session_fields(self) -> repositories.SessionFieldRepository:
        return repositories.SessionFieldRepository()

    @cached_property
    def agenda_items(self) -> AgendaItemRepository:
        return AgendaItemRepository()

    @cached_property
    def content_change_logs(self) -> ContentChangeLogRepository:
        return ContentChangeLogRepository()

    @cached_property
    def spaces(self) -> repositories.SpaceRepository:
        return repositories.SpaceRepository()

    @cached_property
    def time_slots(self) -> repositories.TimeSlotRepository:
        return repositories.TimeSlotRepository()

    @cached_property
    def venues(self) -> repositories.VenueRepository:
        return repositories.VenueRepository()

    @cached_property
    def areas(self) -> repositories.AreaRepository:
        return repositories.AreaRepository()
