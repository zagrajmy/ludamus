from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.propose import ProposeSessionService
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.legacy import (
    EventDTO,
    FacilitatorData,
    FacilitatorDTO,
    NotFoundError,
    OrganizerFieldDTO,
    PersonalDataFieldValueData,
    SessionData,
    SessionFieldValueData,
    SessionStatus,
    TrackDTO,
)
from ludamus.pacts.propose import ProposeRepos
from ludamus.specs.proposal import PROPOSAL_RATE_LIMIT_SECONDS

EXPECTED_SESSION_ID = 99
FACILITATOR_PK = 10
OWN_TRACK_PK = 7
FOREIGN_TRACK_PK = 999
USER_PK = 5
USER_SLUG = "bob"


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.timeouts: dict[str, int | None] = {}

    def get(self, key: str) -> object:
        return self.store.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        self.store[key] = value
        self.timeouts[key] = timeout


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


def _facilitator(*, user_id=None, display_name="Anon Host"):
    return FacilitatorDTO(
        accreditation_type="none",
        display_name=display_name,
        event_id=1,
        pk=FACILITATOR_PK,
        slug="anon-host",
        user_id=user_id,
    )


def _field(pk, slug):
    return OrganizerFieldDTO(
        field_type="text", name=slug, order=0, pk=pk, question="Q", slug=slug
    )


def _session_data(**overrides):
    return {
        "category_id": 3,
        "session_data": {"title": "Test Session", "facilitator_name": "Anon Host"},
        **overrides,
    }


def _expected_session(**overrides):
    data = SessionData(
        event_id=1,
        presenter_id=None,
        facilitator_name="Anon Host",
        category_id=3,
        title="Test Session",
        slug="test-session",
        description="",
        duration="",
        participants_limit=0,
        min_age=0,
        contact_email="",
        status=SessionStatus.PENDING,
    )
    data.update(overrides)
    return data


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
    repos.facilitators.read_by_user_and_event.side_effect = NotFoundError
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
    @pytest.mark.parametrize(
        "wizard_data",
        (
            {"category_id": 1, "session_data": {"description": "No title"}},
            {"category_id": 1},
        ),
    )
    def test_raises_value_error_when_title_missing(self, service, wizard_data):
        with pytest.raises(ValueError, match=r"^session_data must contain 'title'$"):
            service.submit(_event(), wizard_data, user_id=None, user_slug=None)

    def test_anonymous_creates_facilitator_without_user(
        self, service, submitting_repos
    ):
        result = service.submit(_event(), _session_data(), user_id=None, user_slug=None)

        assert result.session_id == EXPECTED_SESSION_ID
        assert result.title == "Test Session"
        submitting_repos.users.read.assert_not_called()
        submitting_repos.facilitators.read_by_user_and_event.assert_not_called()
        submitting_repos.facilitators.slug_exists.assert_called_once_with(
            1, "anon-host"
        )
        submitting_repos.facilitators.create.assert_called_once_with(
            FacilitatorData(
                event_id=1, user_id=None, display_name="Anon Host", slug="anon-host"
            )
        )
        submitting_repos.sessions.slug_exists.assert_called_once_with(1, "test-session")
        submitting_repos.sessions.create.assert_called_once_with(
            _expected_session(), time_slot_ids=[], facilitator_ids=[FACILITATOR_PK]
        )
        submitting_repos.sessions.save_field_values.assert_not_called()
        submitting_repos.personal_data_field_values.save.assert_not_called()
        submitting_repos.tracks.list_public_by_event.assert_not_called()
        submitting_repos.sessions.set_session_tracks.assert_not_called()

    def test_passes_every_wizard_answer_into_the_session(
        self, service, submitting_repos
    ):
        cover_image = object()

        service.submit(
            _event(),
            {
                "category_id": 3,
                "contact_email": "host@example.com",
                "time_slot_ids": [4, 5],
                "session_data": {
                    "title": "Test Session",
                    "facilitator_name": "Anon Host",
                    "description": "Long one",
                    "duration": "2h 30min",
                    "participants_limit": "12",
                    "min_age": "18",
                },
            },
            cover_image=cover_image,
            user_id=None,
            user_slug=None,
        )

        submitting_repos.sessions.create.assert_called_once_with(
            _expected_session(
                description="Long one",
                duration="PT2H30M",
                participants_limit=12,
                min_age=18,
                contact_email="host@example.com",
                cover_image=cover_image,
            ),
            time_slot_ids=[4, 5],
            facilitator_ids=[FACILITATOR_PK],
        )

    def test_retries_slug_until_it_is_free(self, service, submitting_repos):
        submitting_repos.sessions.slug_exists.side_effect = [True, False]

        service.submit(_event(), _session_data(), user_id=None, user_slug=None)

        first, second = submitting_repos.sessions.slug_exists.call_args_list
        assert first == call(1, "test-session")
        assert second.args[0] == 1
        assert second.args[1].startswith("test-session-")
        create_data = submitting_repos.sessions.create.call_args.args[0]
        assert create_data["slug"] == second.args[1]

    def test_logged_in_user_reuses_their_facilitator(self, service, submitting_repos):
        submitting_repos.users.read.return_value = UserDTO.model_construct(
            pk=USER_PK, name="Bob Host"
        )
        submitting_repos.facilitators.read_by_user_and_event.side_effect = None
        submitting_repos.facilitators.read_by_user_and_event.return_value = (
            _facilitator(user_id=USER_PK, display_name="Bob Host")
        )

        service.submit(
            _event(),
            {"category_id": 3, "session_data": {"title": "Test Session"}},
            user_id=USER_PK,
            user_slug=USER_SLUG,
        )

        submitting_repos.users.read.assert_called_once_with(USER_SLUG)
        submitting_repos.facilitators.read_by_user_and_event.assert_called_once_with(
            USER_PK, 1
        )
        submitting_repos.facilitators.create.assert_not_called()
        submitting_repos.sessions.create.assert_called_once_with(
            _expected_session(presenter_id=USER_PK, facilitator_name="Bob Host"),
            time_slot_ids=[],
            facilitator_ids=[FACILITATOR_PK],
        )

    def test_logged_in_user_without_facilitator_gets_one_created(
        self, service, submitting_repos
    ):
        submitting_repos.users.read.return_value = UserDTO.model_construct(
            pk=USER_PK, name="Bob Host"
        )

        service.submit(
            _event(),
            {"category_id": 3, "session_data": {"title": "Test Session"}},
            user_id=USER_PK,
            user_slug=USER_SLUG,
        )

        submitting_repos.facilitators.read_by_user_and_event.assert_called_once_with(
            USER_PK, 1
        )
        submitting_repos.facilitators.create.assert_called_once_with(
            FacilitatorData(
                event_id=1, user_id=USER_PK, display_name="Bob Host", slug="bob-host"
            )
        )

    @pytest.mark.parametrize(
        ("user_id", "user_slug"), ((USER_PK, None), (None, USER_SLUG))
    )
    def test_half_identified_user_is_treated_as_anonymous(
        self, service, submitting_repos, user_id, user_slug
    ):
        service.submit(
            _event(),
            {"category_id": 3, "session_data": {"title": "Test Session"}},
            user_id=user_id,
            user_slug=user_slug,
        )

        submitting_repos.users.read.assert_not_called()
        create_data = submitting_repos.sessions.create.call_args.args[0]
        assert create_data["presenter_id"] is None
        assert not create_data["facilitator_name"]

    def test_skips_blank_session_and_personal_answers(self, service, submitting_repos):
        submitting_repos.session_fields.read_by_slug.side_effect = (
            lambda _event_id, slug: _field({"system": 55, "notes": 56}[slug], slug)
        )
        submitting_repos.personal_fields.read_by_slug.side_effect = (
            lambda _event_id, slug: _field({"email": 1, "phone": 2}[slug], slug)
        )

        result = service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {
                    "title": "Test Session",
                    "facilitator_name": "Anon Host",
                    "session_notes": "   ",
                    "session_notes_custom": "typed",
                    "session_system": "D&D",
                },
                "personal_data": {
                    "other": "ignored",
                    "personal_phone": "",
                    "personal_phone_custom": "typed",
                    "personal_email": "a@x.z",
                },
            },
            user_id=None,
            user_slug=None,
        )

        assert result.session_id == EXPECTED_SESSION_ID
        submitting_repos.session_fields.read_by_slug.assert_called_once_with(
            1, "system"
        )
        submitting_repos.sessions.save_field_values.assert_called_once_with(
            EXPECTED_SESSION_ID,
            [
                SessionFieldValueData(
                    session_id=EXPECTED_SESSION_ID, field_id=55, value="D&D"
                )
            ],
        )
        submitting_repos.personal_fields.read_by_slug.assert_called_once_with(
            1, "email"
        )
        submitting_repos.personal_data_field_values.save.assert_called_once_with(
            [
                PersonalDataFieldValueData(
                    facilitator_id=FACILITATOR_PK, event_id=1, field_id=1, value="a@x.z"
                )
            ]
        )

    def test_skips_answers_to_unknown_fields(self, service, submitting_repos):
        def read_session_field(_event_id, slug):
            if slug == "gone":
                raise NotFoundError
            return _field(55, slug)

        def read_personal_field(_event_id, slug):
            if slug == "gone":
                raise NotFoundError
            return _field(1, slug)

        submitting_repos.session_fields.read_by_slug.side_effect = read_session_field
        submitting_repos.personal_fields.read_by_slug.side_effect = read_personal_field

        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {
                    "title": "Test Session",
                    "facilitator_name": "Anon Host",
                    "session_gone": "old",
                    "session_system": "D&D",
                },
                "personal_data": {"personal_gone": "old", "personal_email": "a@x.z"},
            },
            user_id=None,
            user_slug=None,
        )

        submitting_repos.sessions.save_field_values.assert_called_once_with(
            EXPECTED_SESSION_ID,
            [
                SessionFieldValueData(
                    session_id=EXPECTED_SESSION_ID, field_id=55, value="D&D"
                )
            ],
        )
        submitting_repos.personal_data_field_values.save.assert_called_once_with(
            [
                PersonalDataFieldValueData(
                    facilitator_id=FACILITATOR_PK, event_id=1, field_id=1, value="a@x.z"
                )
            ]
        )

    def test_keeps_only_tracks_of_the_current_event(self, service, submitting_repos):
        result = service.submit(
            _event(),
            _session_data(track_pks=[OWN_TRACK_PK, FOREIGN_TRACK_PK]),
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
            _session_data(track_pks=[FOREIGN_TRACK_PK]),
            user_id=None,
            user_slug=None,
        )

        submitting_repos.sessions.set_session_tracks.assert_not_called()

    def test_skips_int_session_answers(self, service, submitting_repos):
        submitting_repos.session_fields.read_by_slug.return_value = _field(55, "system")

        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {
                    "title": "Test Session",
                    "facilitator_name": "Anon Host",
                    "session_players": 4,
                    "session_system": "D&D",
                },
            },
            user_id=None,
            user_slug=None,
        )

        submitting_repos.session_fields.read_by_slug.assert_called_once_with(
            1, "system"
        )


class TestGetSavedPersonalData:
    def test_returns_empty_for_anonymous(self, service, repos):
        result = service.get_saved_personal_data(event_id=1, user_id=None)

        assert result == {}
        repos.personal_data_field_values.read_for_facilitator_event.assert_not_called()
        repos.facilitators.read_by_user_and_event.assert_not_called()

    def test_returns_empty_when_user_has_no_facilitator(self, service, repos):
        repos.facilitators.read_by_user_and_event.side_effect = NotFoundError

        result = service.get_saved_personal_data(event_id=1, user_id=USER_PK)

        assert result == {}
        repos.facilitators.read_by_user_and_event.assert_called_once_with(USER_PK, 1)
        repos.personal_data_field_values.read_for_facilitator_event.assert_not_called()

    def test_reads_values_of_the_users_facilitator(self, service, repos):
        repos.facilitators.read_by_user_and_event.return_value = _facilitator(
            user_id=USER_PK
        )
        repos.personal_data_field_values.read_for_facilitator_event.return_value = {
            "email": "a@x.z"
        }

        result = service.get_saved_personal_data(event_id=1, user_id=USER_PK)

        assert result == {"email": "a@x.z"}
        repos.facilitators.read_by_user_and_event.assert_called_once_with(USER_PK, 1)
        repos.personal_data_field_values.read_for_facilitator_event.assert_called_once_with(
            FACILITATOR_PK, 1
        )


class TestCheckRateLimit:
    def test_allows_first_submission(self, service, cache):
        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is True
        assert cache.store == {"proposal_rate:1:1.2.3.4": 1}
        assert cache.timeouts == {
            "proposal_rate:1:1.2.3.4": PROPOSAL_RATE_LIMIT_SECONDS
        }

    def test_blocks_second_submission(self, service, cache):
        cache.store["proposal_rate:1:1.2.3.4"] = 1

        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is False

    def test_allows_different_event(self, service, cache):
        cache.store["proposal_rate:1:1.2.3.4"] = 1

        assert service.check_rate_limit(ip="1.2.3.4", event_id=2) is True
