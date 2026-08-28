from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills.propose import ProposeSessionService
from ludamus.pacts.chronology import SessionPlacement
from ludamus.pacts.legacy import (
    EventDTO,
    FacilitatorDTO,
    OrganizerFieldDTO,
    PersonalDataFieldValueData,
    ProposalCategoryDTO,
    SessionFieldValueData,
    TimeSlotDTO,
    TrackDTO,
)
from ludamus.pacts.propose import (
    ONE_PENDING_CLAIM_CONSTRAINT,
    ClaimAlreadyPendingError,
    ProposeRepos,
    SpotClaim,
)
from ludamus.pacts.services import DatabaseConstraintError

EXPECTED_SESSION_ID = 99
FACILITATOR_PK = 10
OWN_TRACK_PK = 7
FOREIGN_TRACK_PK = 999


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
    repos.sessions.count_pending_impromptu_claims.return_value = 0
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


@pytest.fixture(name="timetable")
def timetable_fixture():
    return MagicMock()


@pytest.fixture(name="service")
def service_fixture(repos, cache, timetable):
    return ProposeSessionService(
        transaction=MagicMock(), repos=repos, cache=cache, timetable=timetable
    )


class TestSubmit:
    def test_raises_value_error_when_title_missing(self, service):
        wizard_data = {"category_id": 1, "session_data": {"description": "No title"}}

        with pytest.raises(ValueError, match="session_data must contain 'title'"):
            service.submit(_event(), wizard_data, user_id=None, user_slug=None)

    def test_anonymous_creates_facilitator_without_user(
        self, service, submitting_repos
    ):
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
        submitting_repos.facilitators.create.assert_called_once()
        create_call = submitting_repos.facilitators.create.call_args[0][0]
        assert create_call["user_id"] is None
        assert create_call["display_name"] == "Anon Host"

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

    def test_blocks_second_submission(self, service, cache):
        cache.store["proposal_rate:1:1.2.3.4"] = 1

        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is False

    def test_allows_different_event(self, service, cache):
        cache.store["proposal_rate:1:1.2.3.4"] = 1

        assert service.check_rate_limit(ip="1.2.3.4", event_id=2) is True


def _category(pk, *, start_time=None, end_time=None):
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=end_time,
        max_participants_limit=10,
        min_participants_limit=1,
        name=f"category-{pk}",
        pk=pk,
        slug=f"category-{pk}",
        start_time=start_time,
    )


class TestGetOpenness:
    @pytest.fixture(name="now")
    def now_fixture(self):
        return datetime.now(tz=UTC)

    def test_windowless_category_follows_an_open_event(self, service, repos):
        repos.events.read.return_value = _event()
        repos.categories.list_by_event.return_value = [_category(1)]

        openness = service.get_openness(1)

        assert openness.is_open is True
        assert [c.pk for c in openness.categories] == [1]

    def test_windowless_category_follows_a_closed_event(self, service, repos, now):
        repos.events.read.return_value = _event().model_copy(
            update={"proposal_end_time": now - timedelta(days=1)}
        )
        repos.categories.list_by_event.return_value = [_category(1)]

        openness = service.get_openness(1)

        assert openness.is_open is False
        assert openness.categories == []

    def test_own_window_opens_proposing_on_a_closed_event(self, service, repos, now):
        repos.events.read.return_value = _event().model_copy(
            update={"proposal_end_time": now - timedelta(days=1)}
        )
        repos.categories.list_by_event.return_value = [
            _category(1),
            _category(2, start_time=now - timedelta(hours=1)),
        ]

        openness = service.get_openness(1)

        assert openness.is_open is True
        assert [c.pk for c in openness.categories] == [2]

    def test_lapsed_window_leaves_the_wizard(self, service, repos, now):
        repos.events.read.return_value = _event()
        repos.categories.list_by_event.return_value = [
            _category(1),
            _category(2, end_time=now - timedelta(hours=1)),
        ]

        openness = service.get_openness(1)

        assert openness.is_open is True
        assert [c.pk for c in openness.categories] == [1]

    def test_unpublished_event_is_shut_whatever_the_categories_say(
        self, service, repos, now
    ):
        repos.events.read.return_value = _event().model_copy(
            update={"publication_time": now + timedelta(days=1)}
        )
        repos.categories.list_by_event.return_value = [
            _category(1, start_time=now - timedelta(hours=1))
        ]

        openness = service.get_openness(1)

        assert openness.is_open is False
        assert openness.categories == []
        repos.categories.list_by_event.assert_not_called()


class TestSubmitClaim:
    @staticmethod
    def _claim(service, submitting_repos):
        submitting_repos.users.read.return_value = MagicMock(pk=42, name="Walk Up")
        return service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "Corridor Game", "display_name": "Walk Up"},
            },
            user_id=42,
            user_slug="walk-up",
            spot=SpotClaim(space_pk=3, time_slot_pk=5),
        )

    def test_marks_the_session_impromptu_and_places_it(
        self, service, submitting_repos, timetable
    ):
        submitting_repos.users.read.return_value = MagicMock(pk=42, name="Walk Up")
        slot = TimeSlotDTO(
            pk=5,
            start_time=datetime(2026, 1, 1, 14, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 15, 0, tzinfo=UTC),
        )
        submitting_repos.sessions.read_time_slot.return_value = slot

        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "Corridor Game", "display_name": "Walk Up"},
            },
            user_id=42,
            user_slug="walk-up",
            spot=SpotClaim(space_pk=3, time_slot_pk=5),
        )

        created = submitting_repos.sessions.create.call_args.args[0]
        assert created["is_impromptu"] is True
        timetable.claim_spot.assert_called_once_with(
            session_pk=EXPECTED_SESSION_ID,
            placement=SessionPlacement(
                space_pk=3, start_time=slot.start_time, end_time=slot.end_time
            ),
            event_pk=1,
            user_pk=42,
        )

    def test_a_plain_proposal_is_not_impromptu_and_places_nothing(
        self, service, submitting_repos, timetable
    ):
        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "Test Session", "display_name": "Anon Host"},
            },
            user_id=None,
            user_slug=None,
        )

        created = submitting_repos.sessions.create.call_args.args[0]
        assert created["is_impromptu"] is False
        timetable.claim_spot.assert_not_called()

    def test_an_anonymous_claim_is_refused(self, service, submitting_repos, timetable):
        with pytest.raises(ValueError, match="needs a logged-in author"):
            service.submit(
                _event(),
                {
                    "category_id": 1,
                    "session_data": {"title": "Corridor Game", "display_name": "Anon"},
                },
                user_id=None,
                user_slug=None,
                spot=SpotClaim(space_pk=3, time_slot_pk=5),
            )

        timetable.claim_spot.assert_not_called()


class TestOnePendingClaimCap:
    def test_a_second_claim_is_refused_before_anything_is_written(
        self, service, submitting_repos
    ):
        submitting_repos.sessions.count_pending_impromptu_claims.return_value = 1

        with pytest.raises(ClaimAlreadyPendingError):
            TestSubmitClaim._claim(service, submitting_repos)

        submitting_repos.sessions.create.assert_not_called()

    def test_a_lost_race_on_the_constraint_reads_the_same(
        self, service, submitting_repos
    ):
        submitting_repos.sessions.create.side_effect = DatabaseConstraintError(
            f"duplicate key value violates unique constraint "
            f'"{ONE_PENDING_CLAIM_CONSTRAINT}"'
        )

        with pytest.raises(ClaimAlreadyPendingError):
            TestSubmitClaim._claim(service, submitting_repos)

    def test_any_other_constraint_is_not_reported_as_a_second_claim(
        self, service, submitting_repos
    ):
        submitting_repos.sessions.create.side_effect = DatabaseConstraintError(
            "duplicate key value violates unique constraint "
            '"session_unique_slug_in_event"'
        )

        with pytest.raises(DatabaseConstraintError):
            TestSubmitClaim._claim(service, submitting_repos)

    def test_an_ordinary_proposal_is_not_counted_or_wrapped(
        self, service, submitting_repos
    ):
        service.submit(
            _event(),
            {
                "category_id": 1,
                "session_data": {"title": "Test Session", "display_name": "Anon Host"},
            },
            user_id=None,
            user_slug=None,
        )

        submitting_repos.sessions.count_pending_impromptu_claims.assert_not_called()
