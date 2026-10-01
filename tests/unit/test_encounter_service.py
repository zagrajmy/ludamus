from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.encounter import EncounterService
from ludamus.pacts import EncounterDTO, NotFoundError
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.encounter import EncounterData, EncountersPolicy, RSVPOutcome
from ludamus.pacts.multiverse import SphereRole
from tests.unit.factories import FakeTransaction

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


def _user(pk=CREATOR_ID, **overrides):
    fields = {
        "avatar_url": "",
        "date_joined": START_TIME - timedelta(days=30),
        "discord_username": "",
        "email": f"user{pk}@example.com",
        "full_name": "",
        "is_active": True,
        "is_authenticated": True,
        "is_staff": False,
        "is_superuser": False,
        "name": "",
        "pk": pk,
        "slug": f"user-{pk}",
        "use_gravatar": True,
        "user_type": UserType.ACTIVE,
        "username": "creator",
    }
    return UserDTO(**{**fields, **overrides})


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


class FakeSites:
    def __init__(self, policy):
        self.policy = policy

    def read(self, sphere_id):
        del sphere_id
        return SimpleNamespace(encounters_policy=self.policy)


class FakeUsers:
    def __init__(self, users=()):
        self.users = {user.pk: user for user in users}

    def read_by_id(self, pk):
        try:
            return self.users[pk]
        except KeyError:
            raise NotFoundError from None

    def read_by_ids(self, pks):
        return [self.users[pk] for pk in pks if pk in self.users]


class FakeSpheres:
    def __init__(self, roles=None):
        self.roles = roles or {}

    def manager_role(self, sphere_id, user_slug):
        del sphere_id
        return self.roles.get(user_slug)


class FakeEncounters:
    def __init__(self, rows=(), *, past=()):
        self.rows = {row.pk: row for row in rows}
        self.past = {row.pk: row for row in past}

    def _in_sphere(self, sphere_id):
        return [
            row
            for row in {**self.rows, **self.past}.values()
            if row.sphere_id == sphere_id
        ]

    def create(self, data):
        pk = max(self.rows, default=0) + 1
        self.rows[pk] = _encounter(pk).model_copy(update=dict(data))
        return self.rows[pk]

    def read(self, pk, sphere_id):
        del sphere_id
        return self.rows[pk]

    def read_by_share_code(self, share_code, sphere_id):
        rows = [
            row for row in self._in_sphere(sphere_id) if row.share_code == share_code
        ]
        if not rows:
            raise NotFoundError
        return rows[0]

    def update(self, pk, data):
        self.rows[pk] = self.rows[pk].model_copy(update=dict(data))

    def delete(self, pk):
        del self.rows[pk]

    def list_visible_upcoming(self, sphere_id, user_id, limit):
        del user_id
        rows = [row for row in self.rows.values() if row.sphere_id == sphere_id]
        return rows[:limit] if limit is not None else rows

    def list_visible_past(self, sphere_id, user_id, limit):
        del user_id
        return [row for row in self.past.values() if row.sphere_id == sphere_id][:limit]


class FakeRSVPs:
    def __init__(self, signups=(), *, recent_ips=()):
        # (encounter_id, user_id) pairs
        self.signups = list(signups)
        self.recent_ips = set(recent_ips)

    def create(self, encounter_id, ip_address, user_id):
        self.signups.append((encounter_id, user_id))
        self.recent_ips.add(ip_address)

    def list_by_encounter(self, encounter_id):
        return [
            SimpleNamespace(user_id=user_id)
            for enc, user_id in self.signups
            if enc == encounter_id
        ]

    def count_by_encounter(self, encounter_id):
        return len(self.list_by_encounter(encounter_id))

    def count_by_encounters(self, encounter_ids):
        return {pk: self.count_by_encounter(pk) for pk in encounter_ids}

    def recent_rsvp_exists(self, ip_address, seconds=60):
        del seconds
        return ip_address in self.recent_ips

    def user_has_rsvpd(self, encounter_id, user_id):
        return (encounter_id, user_id) in self.signups

    def delete_by_user(self, encounter_id, user_id):
        self.signups.remove((encounter_id, user_id))


def _service(
    *,
    policy=EncountersPolicy.EVERYONE,
    encounters=None,
    rsvps=None,
    users=None,
    spheres=None,
):
    return EncounterService(
        transaction=FakeTransaction(),
        encounters=encounters or FakeEncounters(),
        rsvps=rsvps or FakeRSVPs(),
        users=users or FakeUsers([_user(CREATOR_ID), _user(OTHER_USER_ID)]),
        spheres=spheres or FakeSpheres(),
        sites=FakeSites(policy),
    )


def _data(**fields):
    return EncounterData(
        creator_id=CREATOR_ID,
        sphere_id=SPHERE_ID,
        title="New night",
        start_time=START_TIME,
        **fields,
    )


class TestEncounterPolicy:
    def test_the_feature_is_off_only_under_the_none_policy(self):
        assert not _service(policy=EncountersPolicy.NONE).enabled(SPHERE_ID)
        assert _service(policy=EncountersPolicy.MANAGERS).enabled(SPHERE_ID)

    def test_everyone_may_create_under_the_open_policy(self):
        assert _service().can_create(sphere_id=SPHERE_ID, user_id=OTHER_USER_ID)

    def test_nobody_may_create_when_the_feature_is_off(self):
        service = _service(policy=EncountersPolicy.NONE)

        assert not service.can_create(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

    def test_a_manager_may_create_under_the_managers_policy(self):
        service = _service(
            policy=EncountersPolicy.MANAGERS,
            spheres=FakeSpheres({f"user-{CREATOR_ID}": SphereRole.MANAGER}),
        )

        assert service.can_create(sphere_id=SPHERE_ID, user_id=CREATOR_ID)


class TestEncounterFeed:
    def test_a_sphere_with_encounters_off_has_an_empty_feed(self):
        service = _service(
            policy=EncountersPolicy.NONE, encounters=FakeEncounters([_encounter(1)])
        )

        feed = service.list_feed(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert (feed.upcoming, feed.past) == ([], [])
        assert service.list_upcoming(sphere_id=SPHERE_ID, user_id=None, limit=3) == []

    def test_feed_marks_mine_counts_signups_and_names_other_organizers(self):
        mine = _encounter(1)
        by_named = _encounter(2).model_copy(update={"creator_id": 30})
        by_username_only = _encounter(3).model_copy(update={"creator_id": 40})
        by_deleted = _encounter(4).model_copy(update={"creator_id": 50})
        service = _service(
            encounters=FakeEncounters(
                [mine, by_named, by_username_only], past=[by_deleted]
            ),
            rsvps=FakeRSVPs([(1, OTHER_USER_ID), (1, 30), (2, CREATOR_ID)]),
            users=FakeUsers(
                [
                    _user(CREATOR_ID),
                    _user(30, name="Ola", full_name="Ola Nowak"),
                    _user(40, username="gm40"),
                ]
            ),
        )

        feed = service.list_feed(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert [
            (i.encounter.pk, i.rsvp_count, i.is_mine, i.organizer_name)
            for i in feed.upcoming
        ] == [(1, 2, True, ""), (2, 1, False, "Ola Nowak"), (3, 0, False, "gm40")]
        assert [(i.encounter.pk, i.organizer_name) for i in feed.past] == [(4, "")]

    def test_upcoming_is_capped_at_the_limit(self):
        service = _service(
            encounters=FakeEncounters([_encounter(1), _encounter(2), _encounter(3)])
        )

        upcoming = service.list_upcoming(sphere_id=SPHERE_ID, user_id=None, limit=2)

        assert [i.encounter.pk for i in upcoming] == [1, 2]
        assert {i.is_mine for i in upcoming} == {False}


class TestEncounterDetail:
    def test_detail_lists_surviving_attendees_and_the_viewers_own_signup(self):
        encounter = _encounter(1, max_participants=5)
        signups = [(1, OTHER_USER_ID), (1, 99)]
        service = _service(
            encounters=FakeEncounters([encounter]), rsvps=FakeRSVPs(signups)
        )

        detail = service.build_detail(
            share_code="CODE1", sphere_id=SPHERE_ID, current_user_id=OTHER_USER_ID
        )

        assert detail.creator.pk == CREATOR_ID
        assert [a.pk for a in detail.attendees] == [OTHER_USER_ID]
        assert detail.rsvp_count == len(signups)
        assert not detail.is_creator
        assert detail.user_has_rsvpd

    def test_anonymous_visitor_sees_the_creators_view_flags_off(self):
        service = _service(encounters=FakeEncounters([_encounter(1)]))

        detail = service.build_detail(
            share_code="CODE1", sphere_id=SPHERE_ID, current_user_id=None
        )

        assert not detail.user_has_rsvpd
        assert not detail.is_creator

    def test_creator_is_recognised_in_the_detail(self):
        service = _service(encounters=FakeEncounters([_encounter(1)]))

        detail = service.build_detail(
            share_code="CODE1", sphere_id=SPHERE_ID, current_user_id=CREATOR_ID
        )

        assert detail.is_creator

    def test_read_by_share_code_is_sphere_scoped(self):
        encounter = _encounter(1)
        service = _service(encounters=FakeEncounters([encounter]))

        assert (
            service.read_by_share_code(share_code="CODE1", sphere_id=SPHERE_ID)
            == encounter
        )
        with pytest.raises(NotFoundError):
            service.read_by_share_code(share_code="CODE1", sphere_id=SPHERE_ID + 1)


class TestEncounterOwnership:
    def test_create_is_refused_when_the_policy_forbids_it(self):
        encounters = FakeEncounters()
        service = _service(policy=EncountersPolicy.MANAGERS, encounters=encounters)

        with pytest.raises(NotFoundError):
            service.create(_data())

        assert not encounters.rows

    def test_create_stores_the_encounter(self):
        encounters = FakeEncounters()

        created = _service(encounters=encounters).create(_data())

        assert created.title == "New night"
        assert encounters.rows == {created.pk: created}

    def test_read_owned_hides_another_users_encounter(self):
        service = _service(encounters=FakeEncounters([_encounter(1)]))

        with pytest.raises(NotFoundError):
            service.read_owned(pk=1, sphere_id=SPHERE_ID, user_id=OTHER_USER_ID)

        assert service.read_owned(pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID).pk == 1

    def test_update_drops_the_public_flag_when_the_owner_may_not_publish(self):
        encounters = FakeEncounters([_encounter(1)])
        service = _service(policy=EncountersPolicy.MANAGERS, encounters=encounters)
        data = EncounterData(title="Renamed", is_public=True)

        updated = service.update_owned(
            pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID, data=data
        )

        assert (updated.title, updated.is_public) == ("Renamed", False)
        assert data == {"title": "Renamed", "is_public": True}

    def test_update_publishes_when_the_policy_allows(self):
        encounters = FakeEncounters([_encounter(1)])

        updated = _service(encounters=encounters).update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data=EncounterData(is_public=True),
        )

        assert updated.is_public

    def test_update_without_the_public_flag_skips_the_policy(self):
        encounters = FakeEncounters([_encounter(1)])
        service = _service(policy=EncountersPolicy.NONE, encounters=encounters)

        updated = service.update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data=EncounterData(game="Catan"),
        )

        assert updated.game == "Catan"

    def test_delete_removes_only_the_owners_encounter(self):
        encounters = FakeEncounters([_encounter(1), _encounter(2)])
        service = _service(encounters=encounters)

        with pytest.raises(NotFoundError):
            service.delete_owned(pk=1, sphere_id=SPHERE_ID, user_id=OTHER_USER_ID)
        service.delete_owned(pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert list(encounters.rows) == [2]


class TestEncounterRSVP:
    def _rsvp(self, service, *, user_id=OTHER_USER_ID, ip="10.0.0.1"):
        return service.rsvp(
            share_code="CODE1", sphere_id=SPHERE_ID, user_id=user_id, ip_address=ip
        )

    def test_a_full_encounter_takes_no_more_signups(self):
        rsvps = FakeRSVPs([(1, 30)])
        service = _service(
            encounters=FakeEncounters([_encounter(1, max_participants=1)]), rsvps=rsvps
        )

        assert self._rsvp(service) == RSVPOutcome.FULL
        assert rsvps.signups == [(1, 30)]

    def test_a_recent_signup_from_the_same_address_is_throttled(self):
        rsvps = FakeRSVPs(recent_ips=["10.0.0.1"])
        service = _service(encounters=FakeEncounters([_encounter(1)]), rsvps=rsvps)

        assert self._rsvp(service) == RSVPOutcome.THROTTLED
        assert not rsvps.signups

    def test_signing_up_twice_is_reported_not_duplicated(self):
        rsvps = FakeRSVPs([(1, OTHER_USER_ID)])
        service = _service(encounters=FakeEncounters([_encounter(1)]), rsvps=rsvps)

        assert self._rsvp(service) == RSVPOutcome.ALREADY_SIGNED_UP
        assert rsvps.signups == [(1, OTHER_USER_ID)]

    def test_an_unlimited_encounter_accepts_the_signup(self):
        rsvps = FakeRSVPs([(1, 30)])
        service = _service(encounters=FakeEncounters([_encounter(1)]), rsvps=rsvps)

        assert self._rsvp(service) == RSVPOutcome.CREATED
        assert rsvps.signups == [(1, 30), (1, OTHER_USER_ID)]

    def test_cancel_removes_the_users_signup(self):
        rsvps = FakeRSVPs([(1, OTHER_USER_ID), (1, 30)])
        service = _service(encounters=FakeEncounters([_encounter(1)]), rsvps=rsvps)

        service.cancel_rsvp(
            share_code="CODE1", sphere_id=SPHERE_ID, user_id=OTHER_USER_ID
        )

        assert rsvps.signups == [(1, 30)]
