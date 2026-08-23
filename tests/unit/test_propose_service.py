from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills.propose import ProposeSessionService
from ludamus.pacts.legacy import (
    EventDTO,
    FacilitatorDTO,
    OrganizerFieldDTO,
    PersonalDataFieldValueData,
    SessionFieldValueData,
    TrackDTO,
)
from ludamus.pacts.propose import ProposeRepos

EXPECTED_SESSION_ID = 99
FACILITATOR_PK = 10
OWN_TRACK_PK = 7
FOREIGN_TRACK_PK = 999


class FakeCache:
    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.store: dict[str, object] = dict(initial or {})

    def get(self, key: str) -> object:
        return self.store.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        del timeout
        self.store[key] = value


def _event(pk=1):
    now = datetime.now(tz=UTC)
    return EventDTO(
        description="Test",
        end_time=now + timedelta(days=7),
        name="Test Event",
        pk=pk,
        proposal_end_time=now + timedelta(days=1),
        proposal_start_time=now - timedelta(days=1),
        publication_time=now - timedelta(days=2),
        slug="test-event",
        sphere_id=1,
        start_time=now + timedelta(days=5),
    )


def _facilitator():
    return FacilitatorDTO(
        accreditation_type="none",
        display_name="Anon Host",
        event_id=1,
        pk=FACILITATOR_PK,
        slug="anon-host",
        user_id=None,
    )


def _field(pk, slug):
    return OrganizerFieldDTO(
        field_type="text", name=slug, order=0, pk=pk, question="Q", slug=slug
    )


@pytest.fixture(name="repos")
def repos_fixture():
    return ProposeRepos(
        events=MagicMock(),
        event_proposal_settings=MagicMock(),
        categories=MagicMock(),
        tracks=MagicMock(),
        sessions=MagicMock(),
        session_fields=MagicMock(),
        personal_fields=MagicMock(),
        personal_data_field_values=MagicMock(),
        facilitators=MagicMock(),
        users=MagicMock(),
    )


@pytest.fixture(name="submitting_repos")
def submitting_repos_fixture(repos):
    repos.sessions.slug_exists.return_value = False
    repos.facilitators.slug_exists.return_value = False
    repos.facilitators.create.return_value = _facilitator()
    repos.sessions.create.return_value = EXPECTED_SESSION_ID
    repos.tracks.list_public_by_event.return_value = [
        TrackDTO.model_construct(pk=OWN_TRACK_PK, event_id=1)
    ]
    return repos


@pytest.fixture(name="cache")
def cache_fixture():
    return FakeCache()


@pytest.fixture(name="service")
def service_fixture(repos, cache):
    return ProposeSessionService(transaction=MagicMock(), repos=repos, cache=cache)


class TestSubmit:
    def test_raises_value_error_when_title_missing(self, service):
        wizard_data = {"category_id": 1, "session_data": {"description": "No title"}}

        with pytest.raises(ValueError, match="session_data must contain 'title'"):
            service.submit(_event(), wizard_data, user_id=None, user_slug=None)

    def test_anonymous_creates_facilitator_without_user(self, service, repos):
        repos.sessions.slug_exists.return_value = False
        repos.facilitators.slug_exists.return_value = False
        repos.facilitators.create.return_value = _facilitator()
        repos.sessions.create.return_value = EXPECTED_SESSION_ID

        result = service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "Test Session", "display_name": "Anon Host"},
            },
            user_id=None,
            user_slug=None,
        )

        assert result.session_id == EXPECTED_SESSION_ID
        assert result.title == "Test Session"
        repos.facilitators.create.assert_called_once()
        create_call = repos.facilitators.create.call_args[0][0]
        assert create_call["user_id"] is None
        assert create_call["display_name"] == "Anon Host"

    def test_skips_blank_session_and_personal_answers(self, service, repos):
        repos.sessions.slug_exists.return_value = False
        repos.facilitators.slug_exists.return_value = False
        repos.facilitators.create.return_value = _facilitator()
        repos.sessions.create.return_value = EXPECTED_SESSION_ID
        repos.session_fields.read_by_slug.side_effect = lambda _event_id, slug: _field(
            {"system": 55, "notes": 56}[slug], slug
        )
        repos.personal_fields.read_by_slug.side_effect = lambda _event_id, slug: _field(
            {"email": 1, "phone": 2}[slug], slug
        )

        result = service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {
                    "title": "Test Session",
                    "display_name": "Anon Host",
                    "session_system": "D&D",
                    "session_notes": "   ",
                },
                "personal_data": {"personal_email": "a@x.z", "personal_phone": ""},
            },
            user_id=None,
            user_slug=None,
        )

        assert result.session_id == EXPECTED_SESSION_ID
        repos.sessions.save_field_values.assert_called_once_with(
            EXPECTED_SESSION_ID,
            [
                SessionFieldValueData(
                    session_id=EXPECTED_SESSION_ID, field_id=55, value="D&D"
                )
            ],
        )
        repos.personal_data_field_values.save.assert_called_once_with(
            [
                PersonalDataFieldValueData(
                    facilitator_id=FACILITATOR_PK, event_id=1, field_id=1, value="a@x.z"
                )
            ]
        )

    def test_keeps_only_tracks_of_the_current_event(self, service, submitting_repos):
        result = service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "Test Session", "display_name": "Anon Host"},
                "track_pks": [OWN_TRACK_PK, FOREIGN_TRACK_PK],
            },
            user_id=None,
            user_slug=None,
        )

        submitting_repos.tracks.list_public_by_event.assert_called_once_with(1)
        submitting_repos.sessions.set_session_tracks.assert_called_once_with(
            result.session_id, [OWN_TRACK_PK]
        )

    def test_attaches_no_tracks_when_all_are_foreign(self, service, submitting_repos):
        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "Test Session", "display_name": "Anon Host"},
                "track_pks": [FOREIGN_TRACK_PK],
            },
            user_id=None,
            user_slug=None,
        )

        submitting_repos.sessions.set_session_tracks.assert_not_called()

    def test_skips_int_session_answers(self, service, submitting_repos):
        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {
                    "title": "Test Session",
                    "display_name": "Anon Host",
                    "session_players": 4,
                },
            },
            user_id=None,
            user_slug=None,
        )

        submitting_repos.session_fields.read_by_slug.assert_not_called()
        submitting_repos.sessions.save_field_values.assert_not_called()


class TestGetSavedPersonalData:
    def test_returns_empty_for_anonymous(self, service, repos):
        result = service.get_saved_personal_data(event_id=1, user_id=None)

        assert result == {}
        repos.personal_data_field_values.read_for_facilitator_event.assert_not_called()
        repos.facilitators.read_by_user_and_event.assert_not_called()


class TestCheckRateLimit:
    def test_allows_first_submission(self, service, cache):
        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is True
        assert "proposal_rate:1:1.2.3.4" in cache.store

    def test_blocks_second_submission(self, repos):
        service = ProposeSessionService(
            transaction=MagicMock(),
            repos=repos,
            cache=FakeCache({"proposal_rate:1:1.2.3.4": 1}),
        )

        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is False

    def test_allows_different_event(self, repos):
        service = ProposeSessionService(
            transaction=MagicMock(),
            repos=repos,
            cache=FakeCache({"proposal_rate:1:1.2.3.4": 1}),
        )

        assert service.check_rate_limit(ip="1.2.3.4", event_id=2) is True
