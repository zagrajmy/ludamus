from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.encounter import EncounterService
from ludamus.pacts import EncounterDTO, EncounterRSVPDTO, NotFoundError
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.encounter import EncounterDetailContextDTO, RSVPOutcome
from ludamus.pacts.legacy import EncounterPublicPolicy
from ludamus.pacts.multiverse import SphereRole

CREATOR_ID = 10
OTHER_USER_ID = 20
SPHERE_ID = 3
START_TIME = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
INDEX_LIST_COUNT = 3


def _encounter(pk=1, *, creator_id=CREATOR_ID, max_participants=0, start_time=None):
    return EncounterDTO(
        creation_time=START_TIME - timedelta(days=7),
        creator_id=creator_id,
        description="",
        end_time=None,
        game="Gloomhaven",
        max_participants=max_participants,
        pk=pk,
        place="",
        share_code=f"CODE{pk}",
        sphere_id=SPHERE_ID,
        start_time=start_time or START_TIME,
        title=f"Encounter {pk}",
    )


def _user(pk=CREATOR_ID, *, full_name="", name="", username="creator"):
    return UserDTO(
        avatar_url="",
        date_joined=START_TIME - timedelta(days=30),
        discord_username="",
        email=f"user{pk}@example.com",
        full_name=full_name,
        is_active=True,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        name=name,
        pk=pk,
        slug=f"user-{pk}",
        use_gravatar=True,
        user_type=UserType.ACTIVE,
        username=username,
    )


def _rsvp(pk=1, *, encounter_id=1, user_id=OTHER_USER_ID):
    return EncounterRSVPDTO(
        creation_time=START_TIME - timedelta(days=1),
        encounter_id=encounter_id,
        ip_address="10.0.0.1",
        pk=pk,
        user_id=user_id,
    )


class TestEncounterService:
    @pytest.fixture
    def collaborators(self):
        # One parent so mock_calls records ordering across the collaborators,
        # not just within each of them.
        return MagicMock()

    @pytest.fixture
    def transaction(self, collaborators):
        return collaborators.transaction

    @pytest.fixture
    def encounters(self, collaborators):
        return collaborators.encounters

    @pytest.fixture
    def rsvps(self, collaborators):
        return collaborators.rsvps

    @pytest.fixture
    def users(self, collaborators):
        return collaborators.users

    @pytest.fixture
    def spheres(self, collaborators):
        return collaborators.spheres

    @pytest.fixture
    def service(self, transaction, encounters, rsvps, users, spheres):
        return EncounterService(
            transaction=transaction,
            encounters=encounters,
            rsvps=rsvps,
            users=users,
            spheres=spheres,
        )

    def test_build_index_merges_mine_and_rsvpd_sorted(
        self, service, encounters, rsvps, users
    ):
        mine = _encounter(1, start_time=START_TIME + timedelta(days=2))
        rsvpd = _encounter(
            2, creator_id=OTHER_USER_ID, start_time=START_TIME + timedelta(days=1)
        )
        encounters.list_upcoming_by_creator.return_value = [mine]
        encounters.list_upcoming_rsvpd.return_value = [rsvpd, mine]
        encounters.list_past.return_value = []
        encounters.list_public_upcoming.return_value = []
        rsvps.count_by_encounters.return_value = {mine.pk: 2, rsvpd.pk: 2}
        users.read_by_ids.return_value = [
            _user(OTHER_USER_ID, full_name="Anna GM", username="anna")
        ]

        result = service.build_index(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert [item.encounter.pk for item in result.upcoming] == [rsvpd.pk, mine.pk]
        assert [item.is_mine for item in result.upcoming] == [False, True]
        assert [item.organizer_name for item in result.upcoming] == ["Anna GM", ""]
        assert [item.rsvp_count for item in result.upcoming] == [2, 2]
        assert result.past == []
        # One batched lookup per list (upcoming, past, public), not one per
        # encounter.
        assert rsvps.count_by_encounters.call_count == INDEX_LIST_COUNT
        encounters.list_upcoming_by_creator.assert_called_once_with(
            SPHERE_ID, CREATOR_ID
        )
        encounters.list_upcoming_rsvpd.assert_called_once_with(SPHERE_ID, CREATOR_ID)
        encounters.list_past.assert_called_once_with(SPHERE_ID, CREATOR_ID)

    def test_build_index_past_falls_back_when_creator_missing(
        self, service, encounters, rsvps, users
    ):
        past = _encounter(5, creator_id=OTHER_USER_ID, start_time=START_TIME)
        encounters.list_upcoming_by_creator.return_value = []
        encounters.list_upcoming_rsvpd.return_value = []
        encounters.list_past.return_value = [past]
        encounters.list_public_upcoming.return_value = []
        rsvps.count_by_encounters.return_value = {past.pk: 1}
        users.read_by_ids.return_value = []

        result = service.build_index(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert result.upcoming == []
        assert [item.organizer_name for item in result.past] == [""]
        assert [item.is_mine for item in result.past] == [False]

    def test_list_public_upcoming_reads_no_personal_lists(
        self, service, encounters, rsvps, users
    ):
        public = _encounter(3, creator_id=OTHER_USER_ID)
        encounters.list_public_upcoming.return_value = [public]
        rsvps.count_by_encounters.return_value = {public.pk: 4}
        users.read_by_ids.return_value = [_user(OTHER_USER_ID, full_name="Anna GM")]

        result = service.list_public_upcoming(sphere_id=SPHERE_ID)

        assert [item.encounter.pk for item in result] == [public.pk]
        assert [item.is_mine for item in result] == [False]
        assert [item.organizer_name for item in result] == ["Anna GM"]
        assert [item.rsvp_count for item in result] == [4]
        encounters.list_upcoming_by_creator.assert_not_called()
        encounters.list_past.assert_not_called()

    def test_build_index_public_excludes_own_upcoming(
        self, service, encounters, rsvps, users
    ):
        mine = _encounter(1)
        other_public = _encounter(2, creator_id=OTHER_USER_ID)
        encounters.list_upcoming_by_creator.return_value = [mine]
        encounters.list_upcoming_rsvpd.return_value = []
        encounters.list_past.return_value = []
        encounters.list_public_upcoming.return_value = [mine, other_public]
        rsvps.count_by_encounters.return_value = {}
        users.read_by_ids.return_value = [_user(OTHER_USER_ID, full_name="Anna GM")]

        result = service.build_index(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert [item.encounter.pk for item in result.upcoming] == [mine.pk]
        assert [item.encounter.pk for item in result.public] == [other_public.pk]

    def test_build_detail_assembles_context_and_skips_missing_attendees(
        self, service, encounters, rsvps, users
    ):
        encounter = _encounter(1, max_participants=3)
        creator = _user(CREATOR_ID)
        attendee = _user(OTHER_USER_ID, username="attendee")
        encounters.read_by_share_code.return_value = encounter
        rsvps.list_by_encounter.return_value = [
            _rsvp(1, user_id=OTHER_USER_ID),
            _rsvp(2, user_id=99),
        ]
        rsvps.user_has_rsvpd.return_value = True

        def read_by_id(pk):
            if pk == CREATOR_ID:
                return creator
            if pk == OTHER_USER_ID:
                return attendee
            raise NotFoundError

        users.read_by_id.side_effect = read_by_id

        result = service.build_detail(
            share_code=encounter.share_code,
            sphere_id=SPHERE_ID,
            current_user_id=OTHER_USER_ID,
        )

        assert isinstance(result, EncounterDetailContextDTO)
        assert result.encounter == encounter
        assert result.creator == creator
        assert result.attendees == [attendee]
        assert result.rsvp_count == len(rsvps.list_by_encounter.return_value)
        assert result.is_full is False
        assert result.spots_remaining == 1
        assert result.is_creator is False
        assert result.user_has_rsvpd is True
        rsvps.user_has_rsvpd.assert_called_once_with(encounter.pk, OTHER_USER_ID)

    def test_build_detail_anonymous_skips_rsvp_lookup(
        self, service, encounters, rsvps, users
    ):
        encounter = _encounter(1)
        encounters.read_by_share_code.return_value = encounter
        users.read_by_id.return_value = _user(CREATOR_ID)
        rsvps.list_by_encounter.return_value = []

        result = service.build_detail(
            share_code=encounter.share_code, sphere_id=SPHERE_ID, current_user_id=None
        )

        assert result.user_has_rsvpd is False
        assert result.spots_remaining is None
        rsvps.user_has_rsvpd.assert_not_called()

    def test_create_delegates_single_insert_without_transaction(
        self, service, transaction, encounters
    ):
        created = _encounter(7)
        encounters.create.return_value = created
        data = {"title": "New", "share_code": "CODE7"}

        result = service.create(data)

        assert result == created
        encounters.create.assert_called_once_with(data)
        transaction.atomic.assert_not_called()

    @pytest.mark.parametrize(
        ("policy", "role", "expected"),
        (
            (EncounterPublicPolicy.DISABLED, SphereRole.MANAGER, False),
            (EncounterPublicPolicy.EVERYONE, None, True),
            (EncounterPublicPolicy.MANAGERS, SphereRole.MANAGER, True),
            (EncounterPublicPolicy.MANAGERS, SphereRole.COMMS, False),
            (EncounterPublicPolicy.MANAGERS, None, False),
        ),
    )
    def test_can_set_public_follows_policy_and_role(
        self, service, spheres, users, policy, role, expected
    ):
        spheres.read.return_value.encounter_public_policy = policy
        spheres.manager_role.return_value = role
        users.read_by_id.return_value = _user(CREATOR_ID)

        assert (
            service.can_set_public(sphere_id=SPHERE_ID, user_id=CREATOR_ID) is expected
        )

    def test_create_strips_public_flag_when_policy_forbids(
        self, service, encounters, spheres
    ):
        spheres.read.return_value.encounter_public_policy = (
            EncounterPublicPolicy.DISABLED
        )
        data = {"sphere_id": SPHERE_ID, "creator_id": CREATOR_ID, "is_public": True}

        service.create(data)

        encounters.create.assert_called_once_with(
            {"sphere_id": SPHERE_ID, "creator_id": CREATOR_ID}
        )

    def test_create_keeps_public_flag_when_policy_allows(
        self, service, encounters, spheres
    ):
        spheres.read.return_value.encounter_public_policy = (
            EncounterPublicPolicy.EVERYONE
        )
        data = {"sphere_id": SPHERE_ID, "creator_id": CREATOR_ID, "is_public": True}

        service.create(data)

        encounters.create.assert_called_once_with(data)

    def test_update_owned_preserves_stored_flag_when_policy_forbids(
        self, service, encounters, spheres
    ):
        spheres.read.return_value.encounter_public_policy = (
            EncounterPublicPolicy.DISABLED
        )
        encounters.read.side_effect = [_encounter(1), _encounter(1)]

        service.update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data={"title": "Renamed", "is_public": False},
        )

        encounters.update.assert_called_once_with(1, {"title": "Renamed"})

    def test_read_owned_returns_own_encounter(self, service, encounters):
        encounter = _encounter(1)
        encounters.read.return_value = encounter

        result = service.read_owned(pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert result == encounter
        encounters.read.assert_called_once_with(1, SPHERE_ID)

    def test_read_owned_rejects_foreign_encounter(self, service, encounters):
        encounters.read.return_value = _encounter(1)

        with pytest.raises(NotFoundError):
            service.read_owned(pk=1, sphere_id=SPHERE_ID, user_id=OTHER_USER_ID)

    def test_update_owned_updates_after_ownership_check(
        self, service, transaction, encounters
    ):
        before = _encounter(1)
        after = _encounter(1)
        encounters.read.side_effect = [before, after]
        data = {"title": "Renamed"}

        result = service.update_owned(
            pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID, data=data
        )

        assert result == after
        encounters.update.assert_called_once_with(1, data)
        assert encounters.read.call_args_list == [
            call(1, SPHERE_ID),
            call(1, SPHERE_ID),
        ]
        transaction.atomic.assert_called_once_with()

    def test_update_owned_foreign_encounter_has_no_side_effects(
        self, service, encounters
    ):
        encounters.read.return_value = _encounter(1)

        with pytest.raises(NotFoundError):
            service.update_owned(
                pk=1, sphere_id=SPHERE_ID, user_id=OTHER_USER_ID, data={"title": "Nope"}
            )

        encounters.update.assert_not_called()

    def test_delete_owned_deletes_after_ownership_check(
        self, service, transaction, encounters
    ):
        encounters.read.return_value = _encounter(1)

        service.delete_owned(pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        encounters.delete.assert_called_once_with(1)
        transaction.atomic.assert_called_once_with()

    def test_delete_owned_foreign_encounter_has_no_side_effects(
        self, service, encounters
    ):
        encounters.read.return_value = _encounter(1)

        with pytest.raises(NotFoundError):
            service.delete_owned(pk=1, sphere_id=SPHERE_ID, user_id=OTHER_USER_ID)

        encounters.delete.assert_not_called()

    def test_rsvp_creates_signup_in_transaction(
        self, service, collaborators, encounters, rsvps
    ):
        encounter = _encounter(1, max_participants=4)
        encounters.read_by_share_code.return_value = encounter
        rsvps.count_by_encounter.return_value = 1
        rsvps.recent_rsvp_exists.return_value = False
        rsvps.user_has_rsvpd.return_value = False

        outcome = service.rsvp(
            share_code=encounter.share_code,
            sphere_id=SPHERE_ID,
            user_id=OTHER_USER_ID,
            ip_address="10.0.0.1",
        )

        assert outcome == RSVPOutcome.CREATED
        assert rsvps.create.call_args == call(encounter.pk, "10.0.0.1", OTHER_USER_ID)
        # Every read the capacity, throttle and duplicate checks depend on has
        # to run between entering and exiting the transaction, or the checks
        # race the insert. Moving any of them out reorders this list.
        assert [name for name, _args, _kwargs in collaborators.mock_calls] == [
            "transaction.atomic",
            "transaction.atomic().__enter__",
            "encounters.read_by_share_code",
            "rsvps.count_by_encounter",
            "rsvps.recent_rsvp_exists",
            "rsvps.user_has_rsvpd",
            "rsvps.create",
            "transaction.atomic().__exit__",
        ]

    def test_rsvp_full_encounter_has_no_side_effects(self, service, encounters, rsvps):
        encounter = _encounter(1, max_participants=2)
        encounters.read_by_share_code.return_value = encounter
        rsvps.count_by_encounter.return_value = 2

        outcome = service.rsvp(
            share_code=encounter.share_code,
            sphere_id=SPHERE_ID,
            user_id=OTHER_USER_ID,
            ip_address="10.0.0.1",
        )

        assert outcome == RSVPOutcome.FULL
        rsvps.create.assert_not_called()

    def test_rsvp_throttles_recent_ip(self, service, encounters, rsvps):
        encounters.read_by_share_code.return_value = _encounter(1)
        rsvps.count_by_encounter.return_value = 0
        rsvps.recent_rsvp_exists.return_value = True

        outcome = service.rsvp(
            share_code="CODE1",
            sphere_id=SPHERE_ID,
            user_id=OTHER_USER_ID,
            ip_address="10.0.0.1",
        )

        assert outcome == RSVPOutcome.THROTTLED
        rsvps.recent_rsvp_exists.assert_called_once_with("10.0.0.1")
        rsvps.create.assert_not_called()

    def test_rsvp_rejects_duplicate_signup(self, service, encounters, rsvps):
        encounter = _encounter(1)
        encounters.read_by_share_code.return_value = encounter
        rsvps.count_by_encounter.return_value = 0
        rsvps.recent_rsvp_exists.return_value = False
        rsvps.user_has_rsvpd.return_value = True

        outcome = service.rsvp(
            share_code=encounter.share_code,
            sphere_id=SPHERE_ID,
            user_id=OTHER_USER_ID,
            ip_address="10.0.0.1",
        )

        assert outcome == RSVPOutcome.ALREADY_SIGNED_UP
        rsvps.user_has_rsvpd.assert_called_once_with(encounter.pk, OTHER_USER_ID)
        rsvps.create.assert_not_called()

    def test_rsvp_propagates_unknown_share_code(self, service, encounters, rsvps):
        encounters.read_by_share_code.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.rsvp(
                share_code="XXXXXX",
                sphere_id=SPHERE_ID,
                user_id=OTHER_USER_ID,
                ip_address="ip",
            )

        rsvps.create.assert_not_called()

    def test_cancel_rsvp_deletes_signup_without_transaction(
        self, service, transaction, encounters, rsvps
    ):
        encounter = _encounter(1)
        encounters.read_by_share_code.return_value = encounter

        service.cancel_rsvp(
            share_code=encounter.share_code, sphere_id=SPHERE_ID, user_id=OTHER_USER_ID
        )

        rsvps.delete_by_user.assert_called_once_with(encounter.pk, OTHER_USER_ID)
        transaction.atomic.assert_not_called()

    def test_cancel_rsvp_propagates_unknown_share_code(
        self, service, encounters, rsvps
    ):
        encounters.read_by_share_code.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.cancel_rsvp(
                share_code="XXXXXX", sphere_id=SPHERE_ID, user_id=OTHER_USER_ID
            )

        rsvps.delete_by_user.assert_not_called()

    def test_read_by_share_code_delegates(self, service, encounters):
        encounter = _encounter(1)
        encounters.read_by_share_code.return_value = encounter

        result = service.read_by_share_code(
            share_code=encounter.share_code, sphere_id=SPHERE_ID
        )

        assert result == encounter
        encounters.read_by_share_code.assert_called_once_with(
            encounter.share_code, SPHERE_ID
        )
