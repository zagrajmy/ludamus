from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills.propose import ProposeSessionService
from ludamus.pacts.legacy import (
    FacilitatorDTO,
    NotFoundError,
    OrganizerFieldDTO,
    PersonalDataFieldValueData,
    SessionFieldValueData,
    TrackDTO,
)
from ludamus.pacts.propose import AccountAnswersDTO, ProposeRepos
from tests.unit.factories import event_dto

EXPECTED_SESSION_ID = 99
FACILITATOR_PK = 10
OWN_TRACK_PK = 7
FOREIGN_TRACK_PK = 999
USER_PK = 5


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    def get(self, key: str) -> object:
        return self.store.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        del timeout
        self.store[key] = value


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


def _facilitator():
    return FacilitatorDTO(
        accreditation_type="none",
        display_name="Anon Host",
        event_id=1,
        pk=FACILITATOR_PK,
        slug="anon-host",
        user_id=None,
    )


def _user():
    user = MagicMock(pk=USER_PK)
    user.name = "Ada"
    return user


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
                    "session_system": "D&D",
                    "session_notes": "   ",
                },
                "personal_data": {"personal_email": "a@x.z", "personal_phone": ""},
            },
            user_id=None,
            user_slug=None,
        )

        assert result.session_id == EXPECTED_SESSION_ID
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
            {
                "category_id": 1,
                "session_data": {
                    "title": "Test Session",
                    "facilitator_name": "Anon Host",
                },
                "track_pks": [OWN_TRACK_PK, FOREIGN_TRACK_PK],
            },
            user_id=None,
            user_slug=None,
        )

        submitting_repos.tracks.list_public_by_event.assert_called_once_with(1)
        submitting_repos.sessions.set_session_tracks.assert_called_once_with(
            result.session_id, [OWN_TRACK_PK]
        )


class TestCheckRateLimit:
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
            service.get_timeslot_requirements(2)
            is repos.categories.list_time_slot_requirements.return_value
        )
        assert (
            service.get_public_tracks(1)
            is repos.tracks.list_public_by_event.return_value
        )

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
        repos.users.read_by_id.return_value = MagicMock(
            email="ada@x.z", discord_username="ada_gm"
        )

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

    def fill_discord_username(self, _slug, handle):
        if self.handle:
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

    def test_keeps_a_handle_the_profile_already_has(self, submitting_repos):
        users = FakeUsers(handle="ada_gm")

        self._submit(self._service(submitting_repos, users), submitting_repos, "bob")

        assert users.handle == "ada_gm"

    def test_skips_a_handle_too_long_for_the_profile(self, submitting_repos):
        users = FakeUsers()

        self._submit(
            self._service(submitting_repos, users), submitting_repos, "x" * 151
        )

        assert not users.handle
