from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.encounter import EncounterService
from ludamus.mills.encounter_calendar import EncounterGuests
from ludamus.pacts import NotFoundError
from ludamus.pacts.encounter import (
    PAST_FEED_LIMIT,
    EncounterData,
    EncounterInviteReason,
    EncountersPolicy,
    InviteeStatus,
    InviteLimitError,
    RSVPOutcome,
)
from ludamus.pacts.multiverse import SphereRole
from ludamus.specs.encounter import (
    CALENDAR_MAILS_PER_CREATOR_PER_DAY,
    INVITEE_RETENTION_AFTER_END,
)
from tests.unit.encounter_fakes import (
    CREATOR_ID,
    OTHER_USER_ID,
    SPHERE_ID,
    START_TIME,
    EncounterWorld,
    FakeEncounters,
    FakeInvitees,
    FakeMailer,
    FakeRSVPs,
    FakeSites,
    FakeSpheres,
    FakeUsers,
    make_encounter,
    make_user,
)
from tests.unit.factories import FakeTransaction


def _service(
    *,
    policy=EncountersPolicy.EVERYONE,
    encounters=None,
    rsvps=None,
    users=None,
    spheres=None,
):
    rsvps = rsvps or FakeRSVPs()
    users = users or FakeUsers([make_user(CREATOR_ID), make_user(OTHER_USER_ID)])
    sites = FakeSites(policy)
    return EncounterService(
        transaction=FakeTransaction(),
        encounters=encounters or FakeEncounters(),
        rsvps=rsvps,
        users=users,
        spheres=spheres or FakeSpheres(),
        sites=sites,
        guests=EncounterGuests(
            rsvps=rsvps,
            invitees=FakeInvitees(users=users, rsvps=rsvps),
            users=users,
            sites=sites,
            mailer=FakeMailer(),
        ),
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
            spheres=FakeSpheres(
                {(SPHERE_ID, f"user-{CREATOR_ID}"): SphereRole.MANAGER}
            ),
        )

        assert service.can_create(sphere_id=SPHERE_ID, user_id=CREATOR_ID)
        assert not service.can_create(sphere_id=SPHERE_ID, user_id=OTHER_USER_ID)

    def test_comms_role_cannot_create_under_a_managers_only_policy(self):
        service = _service(
            policy=EncountersPolicy.MANAGERS,
            spheres=FakeSpheres({(SPHERE_ID, f"user-{CREATOR_ID}"): SphereRole.COMMS}),
        )

        assert not service.can_create(sphere_id=SPHERE_ID, user_id=CREATOR_ID)


class TestEncounterFeed:
    def test_a_sphere_with_encounters_off_has_an_empty_feed(self):
        service = _service(
            policy=EncountersPolicy.NONE, encounters=FakeEncounters([make_encounter(1)])
        )

        feed = service.list_feed(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert (feed.upcoming, feed.past) == ([], [])
        assert service.list_upcoming(sphere_id=SPHERE_ID, user_id=None, limit=3) == []

    def test_feed_marks_mine_counts_signups_and_names_other_organizers(self):
        mine = make_encounter(1)
        by_named = make_encounter(2).model_copy(update={"creator_id": 30})
        by_username_only = make_encounter(3).model_copy(update={"creator_id": 40})
        by_deleted = make_encounter(4).model_copy(update={"creator_id": 50})
        my_past = make_encounter(5)
        service = _service(
            encounters=FakeEncounters(
                [mine, by_named, by_username_only], past=[by_deleted, my_past]
            ),
            rsvps=FakeRSVPs([(1, OTHER_USER_ID), (1, 30), (2, CREATOR_ID)]),
            users=FakeUsers(
                [
                    make_user(CREATOR_ID),
                    make_user(30, name="Ola", full_name="Ola Nowak"),
                    make_user(40, username="gm40"),
                ]
            ),
        )

        feed = service.list_feed(sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert [
            (i.encounter.pk, i.rsvp_count, i.is_mine, i.organizer_name)
            for i in feed.upcoming
        ] == [(1, 2, True, ""), (2, 1, False, "Ola Nowak"), (3, 0, False, "gm40")]
        assert [
            (i.encounter.pk, i.rsvp_count, i.is_mine, i.organizer_name)
            for i in feed.past
        ] == [(4, 0, False, ""), (5, 0, True, "")]

    def test_past_feed_is_capped(self):
        past = [make_encounter(pk) for pk in range(100, 100 + PAST_FEED_LIMIT + 1)]
        service = _service(encounters=FakeEncounters(past=past))

        feed = service.list_feed(sphere_id=SPHERE_ID, user_id=None)

        assert len(feed.past) == PAST_FEED_LIMIT

    def test_upcoming_is_capped_at_the_limit(self):
        service = _service(
            encounters=FakeEncounters(
                [make_encounter(1), make_encounter(2), make_encounter(3)]
            )
        )

        upcoming = service.list_upcoming(sphere_id=SPHERE_ID, user_id=None, limit=2)

        assert [i.encounter.pk for i in upcoming] == [1, 2]
        assert {i.is_mine for i in upcoming} == {False}


class TestEncounterDetail:
    def test_detail_lists_surviving_attendees_and_the_viewers_own_signup(self):
        encounter = make_encounter(1, max_participants=5)
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
        service = _service(encounters=FakeEncounters([make_encounter(1)]))

        detail = service.build_detail(
            share_code="CODE1", sphere_id=SPHERE_ID, current_user_id=None
        )

        assert not detail.user_has_rsvpd
        assert not detail.is_creator

    def test_creator_is_recognised_in_the_detail(self):
        service = _service(encounters=FakeEncounters([make_encounter(1)]))

        detail = service.build_detail(
            share_code="CODE1", sphere_id=SPHERE_ID, current_user_id=CREATOR_ID
        )

        assert detail.is_creator
        assert not detail.user_has_rsvpd

    def test_read_by_share_code_is_sphere_scoped(self):
        encounter = make_encounter(1)
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
            service.create(_data(), invitee_emails=[])

        assert not encounters.rows

    def test_create_stores_the_encounter(self):
        encounters = FakeEncounters()

        created = _service(encounters=encounters).create(_data(), invitee_emails=[])

        assert created.title == "New night"
        assert encounters.rows == {created.pk: created}

    def test_a_manager_creates_under_the_managers_policy(self):
        encounters = FakeEncounters()
        service = _service(
            policy=EncountersPolicy.MANAGERS,
            encounters=encounters,
            spheres=FakeSpheres(
                {(SPHERE_ID, f"user-{CREATOR_ID}"): SphereRole.MANAGER}
            ),
        )

        created = service.create(_data(), invitee_emails=[])

        assert encounters.rows == {created.pk: created}

    def test_read_owned_hides_another_users_encounter(self):
        service = _service(encounters=FakeEncounters([make_encounter(1)]))

        with pytest.raises(NotFoundError):
            service.read_owned(pk=1, sphere_id=SPHERE_ID, user_id=OTHER_USER_ID)

        assert service.read_owned(pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID).pk == 1

    def test_update_drops_the_public_flag_when_the_owner_may_not_publish(self):
        encounters = FakeEncounters([make_encounter(1, is_public=False)])
        service = _service(policy=EncountersPolicy.MANAGERS, encounters=encounters)
        data = EncounterData(title="Renamed", is_public=True)

        updated = service.update_owned(
            pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID, data=data, invitee_emails=[]
        )

        assert (updated.title, updated.is_public) == ("Renamed", False)
        assert data == {"title": "Renamed", "is_public": True}

    def test_update_publishes_when_the_policy_allows(self):
        encounters = FakeEncounters([make_encounter(1)])

        updated = _service(encounters=encounters).update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data=EncounterData(is_public=True),
            invitee_emails=[],
        )

        assert updated.is_public

    def test_update_without_the_public_flag_skips_the_policy(self):
        encounters = FakeEncounters([make_encounter(1)])
        service = _service(policy=EncountersPolicy.NONE, encounters=encounters)

        updated = service.update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data=EncounterData(game="Catan"),
            invitee_emails=[],
        )

        assert updated.game == "Catan"

    def test_delete_removes_only_the_owners_encounter(self):
        encounters = FakeEncounters([make_encounter(1), make_encounter(2)])
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
            encounters=FakeEncounters([make_encounter(1, max_participants=1)]),
            rsvps=rsvps,
        )

        assert self._rsvp(service) == RSVPOutcome.FULL
        assert rsvps.signups == [(1, 30)]

    def test_a_recent_signup_from_the_same_address_is_throttled(self):
        rsvps = FakeRSVPs(recent_ips=["10.0.0.1"])
        service = _service(encounters=FakeEncounters([make_encounter(1)]), rsvps=rsvps)

        assert self._rsvp(service) == RSVPOutcome.THROTTLED
        assert not rsvps.signups

    def test_signing_up_twice_is_reported_not_duplicated(self):
        rsvps = FakeRSVPs([(1, OTHER_USER_ID)])
        service = _service(encounters=FakeEncounters([make_encounter(1)]), rsvps=rsvps)

        assert self._rsvp(service) == RSVPOutcome.ALREADY_SIGNED_UP
        assert rsvps.signups == [(1, OTHER_USER_ID)]

    def test_an_unlimited_encounter_accepts_the_signup(self):
        rsvps = FakeRSVPs([(1, 30)])
        service = _service(encounters=FakeEncounters([make_encounter(1)]), rsvps=rsvps)

        assert self._rsvp(service) == RSVPOutcome.CREATED
        assert rsvps.signups == [(1, 30), (1, OTHER_USER_ID)]

    def test_cancel_removes_the_users_signup(self):
        rsvps = FakeRSVPs([(1, OTHER_USER_ID), (1, 30)])
        service = _service(encounters=FakeEncounters([make_encounter(1)]), rsvps=rsvps)

        service.cancel_rsvp(
            share_code="CODE1", sphere_id=SPHERE_ID, user_id=OTHER_USER_ID
        )

        assert rsvps.signups == [(1, 30)]

    def test_cancel_without_a_signup_changes_nothing_and_mails_nobody(self):
        world = EncounterWorld(encounters=[make_encounter(1)], signups=[(1, 30)])

        world.service().cancel_rsvp(
            share_code="CODE1", sphere_id=SPHERE_ID, user_id=OTHER_USER_ID
        )

        assert world.rsvps.signups == [(1, 30)]
        assert not world.mailer.sent

    def test_an_accepted_invitee_signs_up_on_a_full_encounter(self):
        guest = make_user(OTHER_USER_ID)
        world = EncounterWorld(
            encounters=[make_encounter(1, max_participants=1)],
            invitees={(1, guest.email): InviteeStatus.ACCEPTED},
        )

        outcome = self._rsvp(world.service())

        assert outcome == RSVPOutcome.CREATED
        assert world.rsvps.signups == [(1, OTHER_USER_ID)]
        assert world.mailer.sent == [(EncounterInviteReason.JOINED, guest.email)]


class TestEncounterInvites:
    def test_create_puts_it_in_the_creators_and_each_invitees_calendar(self):
        world = EncounterWorld()

        world.service().create(_data(), invitee_emails=[" Ola@Example.com ", ""])

        assert world.mailer.sent == [
            (EncounterInviteReason.CREATED, f"user{CREATOR_ID}@example.com"),
            (EncounterInviteReason.INVITED, "ola@example.com"),
        ]

    def test_only_the_owner_lists_the_invitees(self):
        world = EncounterWorld(
            encounters=[make_encounter(1)],
            invitees={(1, "ola@example.com"): InviteeStatus.INVITED},
        )
        service = world.service()

        for user_id, sphere_id in ((OTHER_USER_ID, SPHERE_ID), (CREATOR_ID, 99)):
            with pytest.raises(NotFoundError):
                service.read_owned_with_invitees(
                    pk=1, sphere_id=sphere_id, user_id=user_id
                )
        encounter, invitees = service.read_owned_with_invitees(
            pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID
        )

        assert encounter.pk == 1
        assert [i.email for i in invitees] == ["ola@example.com"]

    def test_an_owner_the_policy_no_longer_covers_cannot_invite(self):
        world = EncounterWorld(
            policy=EncountersPolicy.MANAGERS,
            encounters=[make_encounter(1)],
            invitees={(1, "ola@example.com"): InviteeStatus.INVITED},
        )

        world.service().update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data=EncounterData(game="Catan"),
            invitee_emails=["new@example.com"],
        )

        assert world.invitees.rows == {(1, "ola@example.com"): InviteeStatus.INVITED}
        assert not world.mailer.sent

    def test_a_guest_who_declined_is_not_invited_again(self):
        world = EncounterWorld(
            encounters=[make_encounter(1)],
            invitees={(1, "no@example.com"): InviteeStatus.DECLINED},
        )
        service = world.service()

        for emails in ([], ["no@example.com"]):
            service.update_owned(
                pk=1,
                sphere_id=SPHERE_ID,
                user_id=CREATOR_ID,
                data=EncounterData(game="Catan"),
                invitee_emails=emails,
            )

        assert world.invitees.rows == {(1, "no@example.com"): InviteeStatus.DECLINED}
        assert not world.mailer.sent

    def test_edits_past_the_daily_mail_budget_are_refused(self):
        invitees = [f"g{n}@example.com" for n in range(50)]
        world = EncounterWorld(
            encounters=[make_encounter(1)],
            invitees={(1, email): InviteeStatus.INVITED for email in invitees},
        )
        service = world.service()
        moves = CALENDAR_MAILS_PER_CREATOR_PER_DAY // len(invitees)

        def move(hour):
            service.update_owned(
                pk=1,
                sphere_id=SPHERE_ID,
                user_id=CREATOR_ID,
                data=EncounterData(start_time=START_TIME.replace(hour=hour)),
                invitee_emails=invitees,
            )

        for hour in range(moves):
            move(hour)
        with pytest.raises(InviteLimitError):
            move(23)

        assert len(world.mailer.sent) == moves * (len(invitees) + 1)

    def test_signups_never_count_against_the_budget(self):
        world = EncounterWorld(
            encounters=[make_encounter(1)],
            signups=[(1, pk) for pk in range(100, 400)],
            users=[
                make_user(CREATOR_ID, date_joined=datetime.now(UTC)),
                *(make_user(pk) for pk in range(100, 400)),
            ],
        )

        world.service().update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data=EncounterData(start_time=START_TIME.replace(hour=20)),
            invitee_emails=[],
        )

        assert len(world.mailer.sent) == len(range(100, 400)) + 1
        assert world.invitees.count_mailed_since(CREATOR_ID, START_TIME) == 0

    def test_purge_drops_every_row_of_an_encounter_long_over(self):
        world = EncounterWorld(
            encounters=[make_encounter(1)],
            invitees={(1, "kept@example.com"): InviteeStatus.ACCEPTED},
        )

        purged = world.service().purge_stale_invitees(
            now=START_TIME + INVITEE_RETENTION_AFTER_END + timedelta(days=1)
        )

        assert purged == 1
        assert not world.invitees.rows

    def test_purge_drops_removed_and_orphaned_rows_past_the_window(self):
        world = EncounterWorld(
            invitees={
                (1, "kept@example.com"): InviteeStatus.DECLINED,
                (1, "removed@example.com"): InviteeStatus.REMOVED,
            },
            invited_today=["orphan@example.com"],
        )

        purged = world.service().purge_stale_invitees(
            now=datetime.now(UTC) + timedelta(days=2)
        )

        assert purged == len({"removed@example.com", "orphan@example.com"})
        assert world.invitees.rows == {(1, "kept@example.com"): InviteeStatus.DECLINED}

    def test_moving_it_updates_every_guest_and_invites_only_the_new(self):
        world = EncounterWorld(
            encounters=[make_encounter(1)],
            signups=[(1, OTHER_USER_ID)],
            invitees={
                (1, "ola@example.com"): InviteeStatus.INVITED,
                (1, "gone@example.com"): InviteeStatus.DECLINED,
            },
        )
        moved = EncounterData(start_time=START_TIME.replace(hour=20))

        world.service().update_owned(
            pk=1,
            sphere_id=SPHERE_ID,
            user_id=CREATOR_ID,
            data=moved,
            invitee_emails=["ola@example.com", "gone@example.com", "new@example.com"],
        )

        assert world.mailer.sent == [
            (EncounterInviteReason.CHANGED, f"user{CREATOR_ID}@example.com"),
            (EncounterInviteReason.CHANGED, f"user{OTHER_USER_ID}@example.com"),
            (EncounterInviteReason.CHANGED, "ola@example.com"),
            (EncounterInviteReason.INVITED, "new@example.com"),
        ]

    def test_delete_cancels_it_for_every_guest(self):
        world = EncounterWorld(
            encounters=[make_encounter(1)],
            invitees={(1, "ola@example.com"): InviteeStatus.INVITED},
        )

        world.service().delete_owned(pk=1, sphere_id=SPHERE_ID, user_id=CREATOR_ID)

        assert world.mailer.sent == [
            (EncounterInviteReason.DELETED, f"user{CREATOR_ID}@example.com"),
            (EncounterInviteReason.DELETED, "ola@example.com"),
        ]
