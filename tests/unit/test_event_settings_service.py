from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.event_settings import EventSettingsService
from ludamus.pacts.event_settings import EventSettingsRepos, EventSlugTakenError
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.legacy import EventDTO, NotFoundError
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

        event_settings.update_displayed_fields.assert_called_once_with(7, [1])
