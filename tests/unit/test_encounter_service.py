from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.encounter import EncounterService
from ludamus.pacts import EncounterDTO
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.encounter import EncountersPolicy, RSVPOutcome
from ludamus.pacts.multiverse import SphereRole

CREATOR_ID = 10
OTHER_USER_ID = 20
SPHERE_ID = 3
START_TIME = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


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
    def sites(self, collaborators):
        return collaborators.sites

    @pytest.fixture
    def service(self, transaction, encounters, rsvps, users, spheres, sites):
        return EncounterService(
            transaction=transaction,
            encounters=encounters,
            rsvps=rsvps,
            users=users,
            spheres=spheres,
            sites=sites,
        )

    def test_comms_role_cannot_create_under_a_managers_only_policy(
        self, service, sites, spheres, users
    ):
        sites.read.return_value.encounters_policy = EncountersPolicy.MANAGERS
        spheres.manager_role.return_value = SphereRole.COMMS
        users.read_by_id.return_value = _user(CREATOR_ID)

        assert not service.can_create(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

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
