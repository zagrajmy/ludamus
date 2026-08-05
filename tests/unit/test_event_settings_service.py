from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.event_settings import EventSettingsService
from ludamus.pacts.event_settings import (
    EventDisplaySettingsContextDTO,
    EventSettingsRepos,
    EventSlugTakenError,
)
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.legacy import (
    EventDTO,
    EventProposalSettingsDTO,
    EventSettingsDTO,
    NotFoundError,
    ProposalCategoryDTO,
)
from ludamus.pacts.services import DatabaseConstraintError

SPHERE_ID = 10


@contextmanager
def _passthrough():
    yield


def _event(pk=1, slug="conf", sphere_id=SPHERE_ID):
    return EventDTO(
        description="",
        end_time=datetime(2026, 5, 2, tzinfo=UTC),
        name="Conf",
        pk=pk,
        proposal_end_time=None,
        proposal_start_time=None,
        publication_time=None,
        slug=slug,
        sphere_id=sphere_id,
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
    )


def _session_field(pk=1, slug="system", *, is_public=True):
    return OrganizerFieldDTO(
        field_type="text",
        is_public=is_public,
        name="System",
        order=0,
        pk=pk,
        question="Q",
        slug=slug,
    )


def _category(pk=1, name="Talk", slug="talk"):
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=None,
        min_participants_limit=0,
        name=name,
        pk=pk,
        slug=slug,
        start_time=None,
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
        mock = MagicMock()
        mock.savepoint.side_effect = _passthrough
        return mock

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

    def test_update_general_updates_event_in_a_savepoint(
        self, service, transaction, events
    ):
        events.read_by_slug.return_value = _event(pk=7, slug="conf")
        data = {"name": "Renamed", "slug": "new-conf"}

        service.update_general(sphere_id=SPHERE_ID, slug="conf", data=data)

        events.read_by_slug.assert_called_once_with("conf", SPHERE_ID)
        transaction.savepoint.assert_called_once_with()
        events.update.assert_called_once_with(7, data)

    def test_update_general_raises_when_the_new_slug_is_taken(self, service, events):
        events.read_by_slug.side_effect = [
            _event(pk=7, slug="conf"),
            _event(pk=8, slug="new-conf"),
        ]
        events.update.side_effect = DatabaseConstraintError("duplicate key")

        with pytest.raises(EventSlugTakenError):
            service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"name": "Renamed", "slug": "new-conf"},
            )

        assert events.read_by_slug.call_args_list == [
            call("conf", SPHERE_ID),
            call("new-conf", SPHERE_ID),
        ]

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

    def test_update_general_raises_for_event_outside_sphere(self, service, events):
        events.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.update_general(
                sphere_id=SPHERE_ID, slug="foreign", data={"slug": "foreign"}
            )

        events.update.assert_not_called()

    def test_get_display_context_filters_out_non_public_fields(
        self, service, events, event_settings, session_fields
    ):
        events.read_by_slug.return_value = _event(pk=7)
        public_field = _session_field(pk=1, slug="public")
        session_fields.list_by_event.return_value = [
            public_field,
            _session_field(pk=2, slug="hidden", is_public=False),
        ]
        event_settings.read_or_create.return_value = EventSettingsDTO(
            displayed_session_field_ids=[1], pk=5
        )

        context = service.get_display_context(sphere_id=SPHERE_ID, slug="conf")

        assert context == EventDisplaySettingsContextDTO(
            fields=[public_field], displayed_field_ids=[1]
        )
        events.read_by_slug.assert_called_once_with("conf", SPHERE_ID)
        session_fields.list_by_event.assert_called_once_with(7)
        event_settings.read_or_create.assert_called_once_with(7)

    def test_get_display_context_raises_for_event_outside_sphere(
        self, service, events, event_settings, session_fields
    ):
        events.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.get_display_context(sphere_id=SPHERE_ID, slug="foreign")

        session_fields.list_by_event.assert_not_called()
        event_settings.read_or_create.assert_not_called()

    def test_update_displayed_fields_keeps_only_public_field_ids(
        self, service, events, event_settings, session_fields
    ):
        events.read_by_slug.return_value = _event(pk=7)
        session_fields.list_by_event.return_value = [
            _session_field(pk=1, slug="public"),
            _session_field(pk=2, slug="hidden", is_public=False),
        ]

        service.update_displayed_fields(
            sphere_id=SPHERE_ID, slug="conf", selected_ids=[1, 2, 99]
        )

        events.read_by_slug.assert_called_once_with("conf", SPHERE_ID)
        session_fields.list_by_event.assert_called_once_with(7)
        event_settings.update_displayed_fields.assert_called_once_with(7, [1])

    def test_update_displayed_fields_raises_for_event_outside_sphere(
        self, service, events, event_settings
    ):
        events.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.update_displayed_fields(
                sphere_id=SPHERE_ID, slug="foreign", selected_ids=[1]
            )

        event_settings.update_displayed_fields.assert_not_called()

    def test_get_proposal_settings_returns_repo_dto(
        self, service, events, event_proposal_settings
    ):
        events.read_by_slug.return_value = _event(pk=7)
        dto = EventProposalSettingsDTO(
            allow_anonymous_proposals=False, description="d", pk=3
        )
        event_proposal_settings.read_or_create_by_event.return_value = dto

        result = service.get_proposal_settings(sphere_id=SPHERE_ID, slug="conf")

        assert result is dto
        events.read_by_slug.assert_called_once_with("conf", SPHERE_ID)
        event_proposal_settings.read_or_create_by_event.assert_called_once_with(7)

    def test_get_proposal_settings_raises_for_event_outside_sphere(
        self, service, events, event_proposal_settings
    ):
        events.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.get_proposal_settings(sphere_id=SPHERE_ID, slug="foreign")

        event_proposal_settings.read_or_create_by_event.assert_not_called()

    def test_update_proposal_settings_writes_all_settings_in_transaction(
        self, service, transaction, events, event_proposal_settings, proposal_categories
    ):
        events.read_by_slug.return_value = _event(pk=7)
        start = datetime(2026, 4, 1, 10, tzinfo=UTC)
        end = datetime(2026, 4, 15, 18, tzinfo=UTC)

        service.update_proposal_settings(
            sphere_id=SPHERE_ID,
            slug="conf",
            data={
                "description": "CFP is open",
                "proposal_start_time": start,
                "proposal_end_time": end,
                "allow_anonymous_proposals": True,
                "apply_dates_to_categories": False,
            },
        )

        transaction.atomic.assert_called_once_with()
        event_proposal_settings.update_description.assert_called_once_with(
            7, "CFP is open"
        )
        events.update.assert_called_once_with(
            7, {"proposal_start_time": start, "proposal_end_time": end}
        )
        event_proposal_settings.update_allow_anonymous_proposals.assert_called_once_with(
            7, allow=True
        )
        proposal_categories.list_by_event.assert_not_called()
        proposal_categories.update.assert_not_called()

    def test_update_proposal_settings_applies_dates_to_all_categories(
        self, service, events, proposal_categories
    ):
        events.read_by_slug.return_value = _event(pk=7)
        proposal_categories.list_by_event.return_value = [
            _category(pk=1),
            _category(pk=2),
        ]
        start = datetime(2026, 4, 1, 10, tzinfo=UTC)
        end = datetime(2026, 4, 15, 18, tzinfo=UTC)

        service.update_proposal_settings(
            sphere_id=SPHERE_ID,
            slug="conf",
            data={
                "description": "",
                "proposal_start_time": start,
                "proposal_end_time": end,
                "allow_anonymous_proposals": False,
                "apply_dates_to_categories": True,
            },
        )

        proposal_categories.list_by_event.assert_called_once_with(7)
        assert proposal_categories.update.call_args_list == [
            call(1, {"start_time": start, "end_time": end}),
            call(2, {"start_time": start, "end_time": end}),
        ]

    def test_update_proposal_settings_raises_for_event_outside_sphere(
        self, service, transaction, events, event_proposal_settings, proposal_categories
    ):
        events.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.update_proposal_settings(
                sphere_id=SPHERE_ID,
                slug="foreign",
                data={
                    "description": "",
                    "proposal_start_time": None,
                    "proposal_end_time": None,
                    "allow_anonymous_proposals": False,
                    "apply_dates_to_categories": True,
                },
            )

        transaction.atomic.assert_not_called()
        events.update.assert_not_called()
        event_proposal_settings.update_description.assert_not_called()
        proposal_categories.update.assert_not_called()
