from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.propose import ProposeSessionService
from ludamus.pacts.availability import AvailabilityDTO, DayPart
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.legacy import (
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
from ludamus.pacts.propose import AccountAnswersDTO, ProposeRepos
from ludamus.specs.proposal import (
    PROFILE_DISCORD_USERNAME_MAX_LENGTH,
    PROPOSAL_RATE_LIMIT_SECONDS,
)
from tests.unit.factories import event_dto

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
    return event_dto(
        description="Test",
        end_time=now + timedelta(days=7),
        name="Test Event",
        pk=pk,
        proposal_end_time=now + timedelta(days=1),
        proposal_start_time=now - timedelta(days=1),
        publication_time=now - timedelta(days=2),
        slug="test-event",
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


def _user():
    user = MagicMock(pk=USER_PK)
    user.name = "Ada"
    return user


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
            _expected_session(), availability=[], facilitator_ids=[FACILITATOR_PK]
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
                "availability": ["2026-07-10:evening", "not-a-pair"],
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
            availability=[AvailabilityDTO(day=date(2026, 7, 10), part=DayPart.EVENING)],
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
            availability=[],
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

    def test_blocks_a_second_submission_from_the_same_ip(self, service, cache):
        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is True
        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is False
        assert "proposal_rate:1:1.2.3.4" in cache.store


class TestSubmitEdgeCases:
    def test_requires_a_title(self, service, submitting_repos):
        with pytest.raises(ValueError, match="title"):
            service.submit(_event(), {"category_id": 1, "session_data": {}})

        submitting_repos.sessions.create.assert_not_called()

    def test_logged_in_user_reuses_their_facilitator_and_is_the_presenter(
        self, service, submitting_repos
    ):
        submitting_repos.users.read.return_value = _user()
        submitting_repos.facilitators.read_by_user_and_event.side_effect = None
        submitting_repos.facilitators.read_by_user_and_event.return_value = (
            _facilitator()
        )

        service.submit(
            _event(),
            {"category_id": 1, "session_data": {"title": "T"}},
            cover_image=MagicMock(name="cover"),
            user_id=USER_PK,
            user_slug="ada",
        )

        submitting_repos.facilitators.create.assert_not_called()
        create_data = submitting_repos.sessions.create.call_args.args[0]
        assert create_data["presenter_id"] == USER_PK
        assert create_data["facilitator_name"] == "Ada"
        assert "cover_image" in create_data

    def test_logged_in_user_without_a_facilitator_gets_one(
        self, service, submitting_repos
    ):
        submitting_repos.users.read.return_value = _user()
        submitting_repos.facilitators.read_by_user_and_event.side_effect = NotFoundError

        service.submit(
            _event(),
            {"category_id": 1, "session_data": {"title": "T"}},
            user_id=USER_PK,
            user_slug="ada",
        )

        created = submitting_repos.facilitators.create.call_args.args[0]
        assert created["user_id"] == USER_PK
        assert created["display_name"] == "Ada"

    def test_only_foreign_tracks_attaches_none(self, service, submitting_repos):
        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "T"},
                "track_pks": [FOREIGN_TRACK_PK],
            },
        )

        submitting_repos.sessions.set_session_tracks.assert_not_called()

    def test_ignores_write_in_helpers_builtins_and_unknown_fields(
        self, service, submitting_repos
    ):
        submitting_repos.session_fields.read_by_slug.side_effect = NotFoundError
        submitting_repos.personal_fields.read_by_slug.side_effect = NotFoundError

        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {
                    "title": "T",
                    "session_system_custom": "Homebrew",
                    "session_players": 4,
                    "session_ghost": "boo",
                },
                "personal_data": {
                    "other": "x",
                    "personal_diet_custom": "vegan",
                    "personal_diet": "",
                    "personal_ghost": "boo",
                },
            },
        )

        submitting_repos.sessions.save_field_values.assert_not_called()
        submitting_repos.personal_data_field_values.save.assert_not_called()


class TestReads:
    def test_getters_read_through_their_repos(self, service, repos):
        assert service.get_event("slug", 1) is repos.events.read_by_slug.return_value
        assert (
            service.get_proposal_settings(1)
            is repos.event_proposal_settings.read_by_event.return_value
        )
        assert (
            service.get_or_create_proposal_settings(1)
            is repos.event_proposal_settings.read_or_create_by_event.return_value
        )
        assert service.get_categories(1) is repos.categories.list_by_event.return_value
        assert service.get_category(2, 1) is repos.categories.read.return_value
        assert (
            service.get_personal_fields(1)
            is repos.personal_fields.list_by_event.return_value
        )
        assert (
            service.get_session_requirements(2)
            is repos.categories.list_session_field_requirements.return_value
        )
        assert (
            service.asks_availability(2)
            is repos.categories.asks_availability.return_value
        )
        assert (
            service.get_public_tracks(1)
            is repos.tracks.list_public_by_event.return_value
        )
        repos.events.read_by_slug.assert_called_once_with("slug", 1)
        repos.event_proposal_settings.read_by_event.assert_called_once_with(1)
        repos.event_proposal_settings.read_or_create_by_event.assert_called_once_with(1)
        repos.categories.list_by_event.assert_called_once_with(1)
        repos.categories.read.assert_called_once_with(2, 1)
        repos.personal_fields.list_by_event.assert_called_once_with(1)
        repos.categories.list_session_field_requirements.assert_called_once_with(2)
        repos.categories.asks_availability.assert_called_once_with(2)
        repos.tracks.list_public_by_event.assert_called_once_with(1)

    def test_saved_personal_data_is_empty_for_anonymous_or_new_users(
        self, service, repos
    ):
        assert service.get_saved_personal_data(event_id=1, user_id=None) == {}

        repos.facilitators.read_by_user_and_event.side_effect = NotFoundError
        assert service.get_saved_personal_data(event_id=1, user_id=USER_PK) == {}

    def test_saved_personal_data_comes_from_the_users_facilitator(self, service, repos):
        repos.facilitators.read_by_user_and_event.side_effect = None
        repos.facilitators.read_by_user_and_event.return_value = _facilitator()
        repos.personal_data_field_values.read_for_facilitator_event.return_value = {
            "email": "a@x.z"
        }

        assert service.get_saved_personal_data(event_id=1, user_id=USER_PK) == {
            "email": "a@x.z"
        }
        assert (
            repos.personal_data_field_values.read_for_facilitator_event.call_args.args
            == (FACILITATOR_PK, 1)
        )


def _discord_field(slug="dc"):
    return OrganizerFieldDTO(
        field_type="discord", name=slug, order=0, pk=3, question="Q", slug=slug
    )


class TestAccountAnswers:
    def test_anonymous_proposer_has_none(self, service):
        assert (
            service.get_account_answers(user_id=None, fields=[_discord_field()])
            == AccountAnswersDTO()
        )

    def test_profile_handle_answers_only_discord_fields(self, service, repos):
        repos.users.read_by_id.side_effect = {
            USER_PK: MagicMock(email="ada@x.z", discord_username="ada_gm")
        }.__getitem__

        answers = service.get_account_answers(
            user_id=USER_PK, fields=[_discord_field(), _field(4, "phone")]
        )

        assert answers == AccountAnswersDTO(
            email="ada@x.z", personal_data={"personal_dc": "ada_gm"}
        )

    def test_no_profile_handle_answers_nothing(self, service, repos):
        repos.users.read_by_id.return_value = MagicMock(
            email="ada@x.z", discord_username=""
        )

        answers = service.get_account_answers(
            user_id=USER_PK, fields=[_discord_field()]
        )

        assert answers.personal_data == {}


class FakeUsers:
    """Holds one profile handle and fills it only while empty, like the repo."""

    def __init__(self, handle=""):
        self.handle = handle
        self.user = _user()
        self.user.slug = "ada"

    def read(self, _slug):
        return self.user

    def fill_discord_username(self, slug, handle):
        if slug != self.user.slug or self.handle:
            return False
        self.handle = handle
        return True


class TestProfileDiscordFill:
    @staticmethod
    def _submit(service, repos, handle):
        repos.facilitators.read_by_user_and_event.return_value = _facilitator()
        repos.personal_fields.read_by_slug.side_effect = lambda _event_id, slug: (
            _discord_field(slug) if slug == "dc" else _field(4, slug)
        )
        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "T"},
                "personal_data": {"personal_phone": "+48 1", "personal_dc": handle},
            },
            user_id=USER_PK,
            user_slug="ada",
        )

    @staticmethod
    def _service(repos, users):
        return ProposeSessionService(
            transaction=MagicMock(),
            repos=repos._replace(users=users),
            cache=FakeCache(),
        )

    def test_fills_the_empty_profile_handle_with_the_answer(self, submitting_repos):
        users = FakeUsers()

        self._submit(self._service(submitting_repos, users), submitting_repos, " ada ")

        assert users.handle == "ada"

    def test_fills_a_one_character_handle(self, submitting_repos):
        users = FakeUsers()

        self._submit(self._service(submitting_repos, users), submitting_repos, "a")

        assert users.handle == "a"

    def test_fills_a_handle_of_the_profile_max_length(self, submitting_repos):
        users = FakeUsers()
        handle = "x" * PROFILE_DISCORD_USERNAME_MAX_LENGTH

        self._submit(self._service(submitting_repos, users), submitting_repos, handle)

        assert users.handle == handle

    def test_keeps_a_handle_the_profile_already_has(self, submitting_repos):
        users = FakeUsers(handle="ada_gm")

        self._submit(self._service(submitting_repos, users), submitting_repos, "bob")

        assert users.handle == "ada_gm"

    def test_skips_a_handle_too_long_for_the_profile(self, submitting_repos):
        users = FakeUsers()

        self._submit(
            self._service(submitting_repos, users),
            submitting_repos,
            "x" * (PROFILE_DISCORD_USERNAME_MAX_LENGTH + 1),
        )

        assert not users.handle
