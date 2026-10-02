from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.event_settings import EventSettingsService
from ludamus.pacts.event import EventDatesInvalidError, EventPublicationInvalidError
from ludamus.pacts.event_settings import (
    EventSettingsRepos,
    EventSlugTakenError,
    ProposalSettingsUpdateData,
)
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.legacy import (
    EventDTO,
    EventProposalSettingsDTO,
    EventSettingsDTO,
    EventUpdateData,
    NotFoundError,
    ProposalCategoryDTO,
)
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import FakeTransaction, event_dto

SPHERE_ID = 10
_PROPOSALS_OPEN = datetime(2026, 3, 1, tzinfo=UTC)
_PROPOSALS_CLOSE = datetime(2026, 4, 1, tzinfo=UTC)


def _event(pk=1, slug="conf", sphere_id=SPHERE_ID):
    return event_dto(
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        name="Conf",
        pk=pk,
        slug=slug,
        sphere_id=sphere_id,
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
    )


def _session_field(pk=1, slug="system", *, is_public=True, field_type="select"):
    return OrganizerFieldDTO(
        field_type=field_type,
        is_public=is_public,
        name="System",
        order=0,
        pk=pk,
        question="Q",
        slug=slug,
    )


class TestEventSettingsService:
    @pytest.fixture
    def events(self):
        return MagicMock()

    @pytest.fixture
    def event_settings(self):
        return MagicMock()

    @pytest.fixture
    def event_proposal_settings(self):
        return MagicMock()

    @pytest.fixture
    def proposal_categories(self):
        return MagicMock()

    @pytest.fixture
    def session_fields(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        return FakeTransaction()

    @pytest.fixture
    def service(
        self,
        transaction,
        events,
        event_settings,
        event_proposal_settings,
        proposal_categories,
        session_fields,
    ):
        return EventSettingsService(
            transaction=transaction,
            repos=EventSettingsRepos(
                events=events,
                event_settings=event_settings,
                event_proposal_settings=event_proposal_settings,
                proposal_categories=proposal_categories,
                session_fields=session_fields,
            ),
        )

    def test_update_general_raises_when_a_concurrent_rename_takes_the_slug(
        self, service, events
    ):
        # The pre-write read misses, then the loser of the race hits the
        # unique (sphere, slug) index and finds the winner on the retry read.
        events.read_by_slug.side_effect = [
            _event(pk=7, slug="conf"),
            _event(pk=8, slug="new-conf"),
        ]
        events.update.side_effect = DatabaseConstraintError("duplicate key")

        with pytest.raises(EventSlugTakenError) as exc_info:
            service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"name": "Renamed", "slug": "new-conf"},
            )

        assert isinstance(exc_info.value.__cause__, DatabaseConstraintError)

    def test_update_general_propagates_non_slug_constraint_violations(
        self, service, events
    ):
        events.read_by_slug.side_effect = [
            _event(pk=7, slug="conf"),
            _event(pk=7, slug="conf"),
        ]
        events.update.side_effect = DatabaseConstraintError("event_date_times")

        with pytest.raises(DatabaseConstraintError):
            service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"name": "Renamed", "slug": "conf"},
            )

    def test_update_general_propagates_constraint_error_when_slug_is_free(
        self, service, events
    ):
        events.read_by_slug.side_effect = [_event(pk=7, slug="conf"), NotFoundError]
        events.update.side_effect = DatabaseConstraintError("event_date_times")

        with pytest.raises(DatabaseConstraintError):
            service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"name": "Renamed", "slug": "new-conf"},
            )

    def test_update_displayed_fields_keeps_only_public_pill_fields(
        self, service, events, event_settings, session_fields
    ):
        events.read_by_slug.return_value = _event(pk=7)
        session_fields.list_by_event.return_value = [
            _session_field(pk=1, slug="public"),
            _session_field(pk=2, slug="hidden", is_public=False),
            _session_field(pk=3, slug="pitch", field_type="text"),
            _session_field(pk=4, slug="beginners", field_type="checkbox"),
        ]

        service.update_displayed_fields(
            sphere_id=SPHERE_ID, slug="conf", selected_ids=[1, 2, 3, 4, 99]
        )

        event_settings.update_displayed_fields.assert_called_once_with(7, [1, 4])

    def test_update_general_refuses_an_end_not_after_the_start(self, service, events):
        events.read_by_slug.return_value = _event(pk=7)

        with pytest.raises(EventDatesInvalidError):
            service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"end_time": datetime(2026, 5, 1, tzinfo=UTC)},
            )

        events.update.assert_not_called()

    def test_update_general_refuses_publication_after_the_start(self, service, events):
        events.read_by_slug.return_value = _event(pk=7)

        with pytest.raises(EventPublicationInvalidError):
            service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"publication_time": datetime(2026, 5, 1, 1, tzinfo=UTC)},
            )

        events.update.assert_not_called()

    def test_update_general_without_a_slug_keeps_the_constraint_error(
        self, service, events
    ):
        events.read_by_slug.return_value = _event(pk=7)
        events.update.side_effect = DatabaseConstraintError("event_date_times")

        with pytest.raises(DatabaseConstraintError):
            service.update_general(
                sphere_id=SPHERE_ID, slug="conf", data={"name": "Renamed"}
            )


class FakeEvents:
    def __init__(self, event: EventDTO) -> None:
        self.event = event

    def read_by_slug(self, slug: str, sphere_id: int) -> EventDTO:
        if (slug, sphere_id) != (self.event.slug, self.event.sphere_id):
            raise NotFoundError
        return self.event

    def update(self, pk: int, data: EventUpdateData) -> EventDTO:
        self.event = self.event.model_copy(update=dict(data))
        return self.event


class FakeSessionFields:
    def __init__(self, fields: list[OrganizerFieldDTO]) -> None:
        self._fields = fields

    def list_by_event(self, _event_id: int) -> list[OrganizerFieldDTO]:
        return self._fields


class FakeDisplaySettings:
    def __init__(self, displayed: list[int]) -> None:
        self.displayed = displayed

    def read_or_create(self, event_id: int) -> EventSettingsDTO:
        return EventSettingsDTO(pk=event_id, displayed_session_field_ids=self.displayed)


class FakeProposalSettings:
    def __init__(self) -> None:
        self.description = ""
        self.allow_anonymous = False

    def read_or_create_by_event(self, event_id: int) -> EventProposalSettingsDTO:
        return EventProposalSettingsDTO(
            allow_anonymous_proposals=self.allow_anonymous,
            description=self.description,
            pk=event_id,
        )

    def update_description(self, _event_id: int, description: str) -> None:
        self.description = description

    def update_allow_anonymous_proposals(self, _event_id: int, *, allow: bool) -> None:
        self.allow_anonymous = allow


class FakeProposalCategories:
    def __init__(self, categories: list[ProposalCategoryDTO]) -> None:
        self.rows = {category.pk: category for category in categories}

    def list_by_event(self, _event_id: int) -> list[ProposalCategoryDTO]:
        return list(self.rows.values())

    def update(self, pk: int, data: dict[str, object]) -> ProposalCategoryDTO:
        self.rows[pk] = self.rows[pk].model_copy(update=data)
        return self.rows[pk]


def _category(pk: int) -> ProposalCategoryDTO:
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=None,
        max_participants_limit=10,
        min_participants_limit=1,
        name="RPG",
        pk=pk,
        slug="rpg",
        start_time=None,
    )


class _Fakes:
    def __init__(
        self,
        *,
        fields: list[OrganizerFieldDTO] | None = None,
        displayed: list[int] | None = None,
        categories: list[ProposalCategoryDTO] | None = None,
    ) -> None:
        self.events = FakeEvents(_event(pk=7))
        self.session_fields = FakeSessionFields(fields or [])
        self.display = FakeDisplaySettings(displayed or [])
        self.proposal = FakeProposalSettings()
        self.categories = FakeProposalCategories(categories or [])
        self.service = EventSettingsService(
            transaction=FakeTransaction(),
            repos=EventSettingsRepos(
                events=self.events,
                event_settings=self.display,
                event_proposal_settings=self.proposal,
                proposal_categories=self.categories,
                session_fields=self.session_fields,
            ),
        )


def _proposal_data(*, apply_to_categories: bool) -> ProposalSettingsUpdateData:
    return ProposalSettingsUpdateData(
        description="Send us your games",
        proposal_start_time=_PROPOSALS_OPEN,
        proposal_end_time=_PROPOSALS_CLOSE,
        allow_anonymous_proposals=True,
        apply_dates_to_categories=apply_to_categories,
    )


class TestDisplayAndProposalSettings:
    def test_display_context_offers_public_pill_fields_and_says_others_exist(self):
        fakes = _Fakes(
            fields=[
                _session_field(pk=1, slug="public"),
                _session_field(pk=2, slug="hidden", is_public=False),
                _session_field(pk=3, slug="pitch", field_type="text"),
                _session_field(pk=4, slug="beginners", field_type="checkbox"),
            ],
            displayed=[1],
        )

        context = fakes.service.get_display_context(sphere_id=SPHERE_ID, slug="conf")

        assert [field.pk for field in context.fields] == [1, 4]
        assert context.displayed_field_ids == [1]
        assert context.has_any_fields is True

    def test_display_context_of_an_event_without_fields(self):
        fakes = _Fakes()

        context = fakes.service.get_display_context(sphere_id=SPHERE_ID, slug="conf")

        assert not context.fields
        assert context.has_any_fields is False

    def test_proposal_settings_are_read_for_the_event(self):
        fakes = _Fakes()
        fakes.proposal.description = "Rules"

        settings = fakes.service.get_proposal_settings(sphere_id=SPHERE_ID, slug="conf")

        assert settings.description == "Rules"
        assert settings.pk == fakes.events.event.pk

    def test_update_proposal_settings_writes_dates_text_and_anonymity(self):
        fakes = _Fakes(categories=[_category(pk=1)])

        fakes.service.update_proposal_settings(
            sphere_id=SPHERE_ID,
            slug="conf",
            data=_proposal_data(apply_to_categories=False),
        )

        assert fakes.events.event.proposal_start_time == _PROPOSALS_OPEN
        assert fakes.events.event.proposal_end_time == _PROPOSALS_CLOSE
        assert fakes.proposal.description == "Send us your games"
        assert fakes.proposal.allow_anonymous is True
        assert fakes.categories.rows[1].start_time is None

    def test_update_proposal_settings_can_push_the_dates_onto_every_category(self):
        fakes = _Fakes(categories=[_category(pk=1), _category(pk=2)])

        fakes.service.update_proposal_settings(
            sphere_id=SPHERE_ID,
            slug="conf",
            data=_proposal_data(apply_to_categories=True),
        )

        assert all(
            (category.start_time, category.end_time)
            == (_PROPOSALS_OPEN, _PROPOSALS_CLOSE)
            for category in fakes.categories.rows.values()
        )

    def test_an_event_of_another_sphere_is_not_found_before_any_write(self):
        fakes = _Fakes(categories=[_category(pk=1)])

        with pytest.raises(NotFoundError):
            fakes.service.update_proposal_settings(
                sphere_id=SPHERE_ID + 1,
                slug="conf",
                data=_proposal_data(apply_to_categories=True),
            )

        assert fakes.proposal.allow_anonymous is False
        assert fakes.categories.rows[1].start_time is None
