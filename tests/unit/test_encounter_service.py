from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills.encounter import EncounterService
from ludamus.pacts import EncounterDTO
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.multiverse import SphereRole

CREATOR_ID = 10
OTHER_USER_ID = 20
SPHERE_ID = 3
START_TIME = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _encounter(pk=1, *, max_participants=0):
    return EncounterDTO(
        creation_time=START_TIME - timedelta(days=7),
        creator_id=CREATOR_ID,
        description="",
        end_time=None,
        game="Gloomhaven",
        max_participants=max_participants,
        pk=pk,
        place="",
        share_code=f"CODE{pk}",
        sphere_id=SPHERE_ID,
        start_time=START_TIME,
        title=f"Encounter {pk}",
    )


def _user(pk=CREATOR_ID):
    return UserDTO(
        avatar_url="",
        date_joined=START_TIME - timedelta(days=30),
        discord_username="",
        email=f"user{pk}@example.com",
        full_name="",
        is_active=True,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        name="",
        pk=pk,
        slug=f"user-{pk}",
        use_gravatar=True,
        user_type=UserType.ACTIVE,
        username="creator",
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
    def service(self, collaborators):
        return EncounterService(
            transaction=collaborators.transaction,
            encounters=collaborators.encounters,
            rsvps=collaborators.rsvps,
            users=collaborators.users,
            spheres=collaborators.spheres,
            sites=collaborators.sites,
            guests=collaborators.guests,
        )

    def test_comms_role_cannot_create_under_a_managers_only_policy(
        self, service, sites, spheres, users
    ):
        sites.read.return_value.encounters_policy = EncountersPolicy.MANAGERS
        spheres.manager_role.return_value = SphereRole.COMMS
        users.read_by_id.return_value = _user(CREATOR_ID)

        assert not service.can_create(sphere_id=SPHERE_ID, user_id=CREATOR_ID)
