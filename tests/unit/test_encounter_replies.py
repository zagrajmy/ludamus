from ludamus.mills.encounter_calendar import encounter_calendar_uid
from ludamus.mills.encounter_replies import EncounterReplyService
from ludamus.pacts.calendar import CalendarReply, PartStat
from ludamus.pacts.encounter import (
    EncounterInviteReason,
    EncountersPolicy,
    InviteeStatus,
    ReplyOutcome,
)
from tests.unit.encounter_fakes import (
    CREATOR_ID,
    OTHER_USER_ID,
    EncounterWorld,
    FakeReplyAddresses,
    make_encounter,
)
from tests.unit.factories import FakeTransaction

CREATOR_EMAIL = f"user{CREATOR_ID}@example.com"
OTHER_EMAIL = f"user{OTHER_USER_ID}@example.com"
STRANGER_EMAIL = "ola@example.com"


def _answer(world, *, email, partstat, address=None, share_code="CODE1"):
    uid = encounter_calendar_uid(share_code)
    service = EncounterReplyService(
        transaction=FakeTransaction(),
        encounters=world.encounters,
        rsvps=world.rsvps,
        users=world.users,
        guests=world.guests,
        reply_addresses=FakeReplyAddresses(),
        sites=world.sites,
    )
    return service.apply_calendar_reply(
        address=address
        or FakeReplyAddresses.address_for(uid=uid, attendee_email=email),
        reply=CalendarReply(uid=uid, attendee_email=email, partstat=partstat),
    )


def _world(*, max_participants=0, **kwargs):
    return EncounterWorld(
        encounters=[make_encounter(1, max_participants=max_participants)], **kwargs
    )


class TestReplyGate:
    def test_a_reply_to_someone_elses_address_is_forged(self):
        world = _world(invitees={(1, OTHER_EMAIL): InviteeStatus.INVITED})

        outcome = _answer(
            world,
            email=OTHER_EMAIL,
            partstat=PartStat.ACCEPTED,
            address=FakeReplyAddresses.address_for(
                uid=encounter_calendar_uid("CODE1"), attendee_email=STRANGER_EMAIL
            ),
        )

        assert outcome == ReplyOutcome.FORGED
        assert not world.rsvps.signups

    def test_a_reply_for_a_deleted_encounter_is_ignored(self):
        outcome = _answer(
            _world(), email=OTHER_EMAIL, partstat=PartStat.ACCEPTED, share_code="GONE"
        )

        assert outcome == ReplyOutcome.IGNORED

    def test_a_sphere_that_stopped_running_encounters_ignores_replies(self):
        world = _world(
            policy=EncountersPolicy.NONE,
            invitees={(1, OTHER_EMAIL): InviteeStatus.INVITED},
        )

        outcome = _answer(world, email=OTHER_EMAIL, partstat=PartStat.ACCEPTED)

        assert outcome == ReplyOutcome.IGNORED
        assert world.invitees.rows == {(1, OTHER_EMAIL): InviteeStatus.INVITED}

    def test_a_tentative_answer_changes_nothing(self):
        world = _world(invitees={(1, OTHER_EMAIL): InviteeStatus.INVITED})

        outcome = _answer(world, email=OTHER_EMAIL, partstat=PartStat.TENTATIVE)

        assert outcome == ReplyOutcome.IGNORED
        assert world.invitees.rows == {(1, OTHER_EMAIL): InviteeStatus.INVITED}


class TestAccept:
    def test_an_invitee_with_an_account_is_signed_up(self):
        world = _world(invitees={(1, OTHER_EMAIL): InviteeStatus.INVITED})

        outcome = _answer(world, email=OTHER_EMAIL, partstat=PartStat.ACCEPTED)

        assert outcome == ReplyOutcome.ACCEPTED
        assert world.rsvps.signups == [(1, OTHER_USER_ID)]
        assert world.invitees.rows == {(1, OTHER_EMAIL): InviteeStatus.ACCEPTED}
        assert not world.mailer.sent

    def test_an_invitee_without_an_account_holds_a_spot(self):
        world = _world(invitees={(1, STRANGER_EMAIL): InviteeStatus.INVITED})

        outcome = _answer(world, email=STRANGER_EMAIL, partstat=PartStat.ACCEPTED)

        assert outcome == ReplyOutcome.ACCEPTED
        assert not world.rsvps.signups
        assert world.invitees.rows == {(1, STRANGER_EMAIL): InviteeStatus.ACCEPTED}

    def test_the_creator_and_the_signed_up_are_already_in(self):
        world = _world(
            signups=[(1, OTHER_USER_ID)],
            invitees={(1, OTHER_EMAIL): InviteeStatus.INVITED},
        )

        for email in (CREATOR_EMAIL, OTHER_EMAIL):
            assert (
                _answer(world, email=email, partstat=PartStat.ACCEPTED)
                == ReplyOutcome.IGNORED
            )
        assert world.rsvps.signups == [(1, OTHER_USER_ID)]

    def test_only_an_invitee_still_on_the_list_may_accept(self):
        world = _world(invitees={(1, STRANGER_EMAIL): InviteeStatus.REMOVED})

        for email in (STRANGER_EMAIL, "never@example.com"):
            assert (
                _answer(world, email=email, partstat=PartStat.ACCEPTED)
                == ReplyOutcome.IGNORED
            )
        assert world.invitees.rows == {(1, STRANGER_EMAIL): InviteeStatus.REMOVED}

    def test_a_repeated_acceptance_takes_no_second_spot(self):
        world = _world(
            max_participants=1, invitees={(1, STRANGER_EMAIL): InviteeStatus.ACCEPTED}
        )

        outcome = _answer(world, email=STRANGER_EMAIL, partstat=PartStat.ACCEPTED)

        assert outcome == ReplyOutcome.IGNORED
        assert not world.mailer.sent

    def test_accepting_a_full_encounter_cancels_the_event_for_the_guest(self):
        world = _world(
            max_participants=1,
            signups=[(1, CREATOR_ID)],
            invitees={
                (1, OTHER_EMAIL): InviteeStatus.INVITED,
                (1, STRANGER_EMAIL): InviteeStatus.INVITED,
            },
        )

        outcomes = [
            _answer(world, email=email, partstat=PartStat.ACCEPTED)
            for email in (OTHER_EMAIL, STRANGER_EMAIL)
        ]

        assert outcomes == [ReplyOutcome.FULL, ReplyOutcome.FULL]
        assert world.rsvps.signups == [(1, CREATOR_ID)]
        assert [
            (i.reason, i.attendee_email, i.attendee_name, i.partstat)
            for i in world.mailer.invites
        ] == [
            (EncounterInviteReason.FULL, OTHER_EMAIL, "", PartStat.ACCEPTED),
            (EncounterInviteReason.FULL, STRANGER_EMAIL, "", PartStat.NEEDS_ACTION),
        ]


class TestDecline:
    def test_declining_removes_the_signup_and_marks_the_invitee(self):
        world = _world(
            signups=[(1, OTHER_USER_ID)],
            invitees={(1, OTHER_EMAIL): InviteeStatus.ACCEPTED},
        )

        outcome = _answer(world, email=OTHER_EMAIL, partstat=PartStat.DECLINED)

        assert outcome == ReplyOutcome.DECLINED
        assert not world.rsvps.signups
        assert world.invitees.rows == {(1, OTHER_EMAIL): InviteeStatus.DECLINED}

    def test_an_invitee_without_an_account_can_decline(self):
        world = _world(invitees={(1, STRANGER_EMAIL): InviteeStatus.INVITED})

        outcome = _answer(world, email=STRANGER_EMAIL, partstat=PartStat.DECLINED)

        assert outcome == ReplyOutcome.DECLINED
        assert world.invitees.rows == {(1, STRANGER_EMAIL): InviteeStatus.DECLINED}

    def test_a_decline_from_someone_neither_invited_nor_signed_up_is_ignored(self):
        world = _world()

        outcome = _answer(world, email=OTHER_EMAIL, partstat=PartStat.DECLINED)

        assert outcome == ReplyOutcome.IGNORED
        assert not world.invitees.rows
