from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from ludamus.mills.encounter_calendar import (
    Guest,
    encounter_calendar_uid,
    encounter_share_code,
)
from ludamus.pacts.calendar import PartStat
from ludamus.pacts.encounter import (
    EncounterInviteReason,
    InviteeStatus,
    InviteLimitError,
)
from ludamus.specs.encounter import (
    CALENDAR_MAILS_PER_NEW_CREATOR_PER_DAY,
    ENCOUNTER_DEFAULT_DURATION,
    INVITEES_PER_CREATOR_PER_DAY,
    INVITEES_PER_NEW_CREATOR_PER_DAY,
    NEW_CREATOR_AGE,
)
from tests.unit.encounter_fakes import (
    CREATOR_ID,
    OTHER_USER_ID,
    START_TIME,
    EncounterWorld,
    make_encounter,
    make_user,
)

CREATOR_EMAIL = f"user{CREATOR_ID}@example.com"
OTHER_EMAIL = f"user{OTHER_USER_ID}@example.com"


class TestCalendarUid:
    def test_share_code_round_trips_through_the_uid(self):
        assert encounter_share_code(encounter_calendar_uid("CODE1")) == "CODE1"

    def test_a_uid_from_elsewhere_names_no_encounter(self):
        assert not encounter_share_code("CODE1@google.com")


class TestRoom:
    def test_an_encounter_without_a_limit_always_has_room(self):
        world = EncounterWorld(signups=[(1, n) for n in range(30)])

        assert world.guests.has_room(make_encounter(1), email=OTHER_EMAIL)

    def test_an_accepted_invitee_without_an_account_takes_a_spot(self):
        world = EncounterWorld(
            invitees={(1, "ola@example.com"): InviteeStatus.ACCEPTED}
        )

        assert not world.guests.has_room(
            make_encounter(1, max_participants=1), email=OTHER_EMAIL
        )

    def test_the_accepted_invitee_keeps_their_own_spot(self):
        world = EncounterWorld(
            invitees={(1, "ola@example.com"): InviteeStatus.ACCEPTED}
        )
        encounter = make_encounter(1, max_participants=1)

        assert world.guests.has_room(encounter, email="ola@example.com")
        assert not world.guests.has_room(encounter, email=OTHER_EMAIL)


class TestReplaceInvitees:
    def test_new_addresses_past_the_daily_limit_are_refused_whole(self):
        earlier = {f"g{n}@example.com" for n in range(INVITEES_PER_CREATOR_PER_DAY)}
        world = EncounterWorld(invited_today=earlier)

        with pytest.raises(InviteLimitError):
            world.guests.replace_invitees(
                make_encounter(1), ["new@example.com"], creator=make_user()
            )

        assert not world.invitees.list_by_encounter(1)
        assert not world.mailer.sent

    def test_a_week_old_account_has_the_smaller_allowance(self):
        world = EncounterWorld()
        fresh = make_user(date_joined=datetime.now(UTC) - timedelta(days=1))
        emails = [f"g{n}@example.com" for n in range(INVITEES_PER_NEW_CREATOR_PER_DAY)]

        world.guests.replace_invitees(make_encounter(1), emails, creator=fresh)
        with pytest.raises(InviteLimitError):
            world.guests.replace_invitees(
                make_encounter(2), ["one-more@example.com"], creator=fresh
            )

        assert len(world.invitees.list_by_encounter(1)) == len(emails)
        assert not world.invitees.list_by_encounter(2)

    @freeze_time(START_TIME)
    def test_an_account_exactly_a_week_old_has_the_full_allowance(self):
        world = EncounterWorld()
        week_old = make_user(date_joined=START_TIME - NEW_CREATOR_AGE)
        emails = [
            f"g{n}@example.com" for n in range(INVITEES_PER_NEW_CREATOR_PER_DAY + 1)
        ]

        added = world.guests.replace_invitees(
            make_encounter(1), emails, creator=week_old
        )

        assert added == set(emails)

    def test_a_removed_address_put_back_is_invited_again(self):
        world = EncounterWorld(invitees={(1, "ola@example.com"): InviteeStatus.REMOVED})

        added = world.guests.replace_invitees(
            make_encounter(1), ["ola@example.com"], creator=make_user()
        )

        assert added == {"ola@example.com"}
        assert world.invitees.rows == {(1, "ola@example.com"): InviteeStatus.INVITED}

    def test_inviting_an_address_already_counted_today_is_free(self):
        earlier = {f"g{n}@example.com" for n in range(INVITEES_PER_CREATOR_PER_DAY)}
        world = EncounterWorld(invited_today=earlier)

        added = world.guests.replace_invitees(
            make_encounter(1), ["g0@example.com"], creator=make_user()
        )

        assert added == {"g0@example.com"}

    def test_the_creator_never_invites_themselves(self):
        world = EncounterWorld()

        added = world.guests.replace_invitees(
            make_encounter(1), [CREATOR_EMAIL.upper()], creator=make_user()
        )

        assert not added

    def test_a_removed_invitee_is_cancelled_unless_they_signed_up(self):
        world = EncounterWorld(
            signups=[(1, OTHER_USER_ID)],
            invitees={
                (1, "ola@example.com"): InviteeStatus.INVITED,
                (1, OTHER_EMAIL): InviteeStatus.ACCEPTED,
            },
        )

        world.guests.replace_invitees(make_encounter(1), [], creator=make_user())

        assert world.mailer.sent == [
            (EncounterInviteReason.UNINVITED, "ola@example.com")
        ]
        assert world.invitees.rows == {
            (1, "ola@example.com"): InviteeStatus.REMOVED,
            (1, OTHER_EMAIL): InviteeStatus.REMOVED,
        }


class TestGuests:
    def test_guests_are_the_creator_signups_and_invitees_still_answering(self):
        world = EncounterWorld(
            signups=[(1, OTHER_USER_ID)],
            invitees={
                (1, "ola@example.com"): InviteeStatus.INVITED,
                (1, "no@example.com"): InviteeStatus.DECLINED,
                (1, "gone@example.com"): InviteeStatus.REMOVED,
            },
        )

        guests = world.guests.guests(make_encounter(1))

        assert [(g.email, g.partstat, g.asks_reply) for g in guests] == [
            (CREATOR_EMAIL, PartStat.ACCEPTED, False),
            (OTHER_EMAIL, PartStat.ACCEPTED, True),
            ("ola@example.com", PartStat.NEEDS_ACTION, True),
        ]

    def test_an_invitee_with_an_account_is_named_after_it(self):
        ola = make_user(30, email="ola@example.com", name="Ola")
        world = EncounterWorld(
            users=[make_user(CREATOR_ID), ola],
            invitees={(1, "ola@example.com"): InviteeStatus.ACCEPTED},
        )

        guests = world.guests.guests(make_encounter(1))

        assert [(g.email, g.name, g.partstat) for g in guests][1:] == [
            ("ola@example.com", "Ola", PartStat.ACCEPTED)
        ]

    def test_members_without_an_address_or_an_account_get_no_invite(self):
        world = EncounterWorld(
            users=[make_user(CREATOR_ID, email=""), make_user(OTHER_USER_ID)],
            signups=[(1, OTHER_USER_ID), (1, 99)],
        )

        guests = world.guests.guests(make_encounter(1))

        assert [g.email for g in guests] == [OTHER_EMAIL]


class TestSend:
    def test_a_deleted_creators_invites_name_the_sphere(self):
        world = EncounterWorld(
            users=[make_user(OTHER_USER_ID)], signups=[(1, OTHER_USER_ID)]
        )

        world.guests.send(
            make_encounter(1),
            reason=EncounterInviteReason.CHANGED,
            guests=world.guests.guests(make_encounter(1)),
        )

        assert [(i.organizer_name, i.attendee_email) for i in world.mailer.invites] == [
            ("Sphere", OTHER_EMAIL)
        ]

    def test_each_invite_carries_the_encounters_uid_and_default_end(self):
        world = EncounterWorld(users=[make_user(CREATOR_ID, name="Ola")])

        world.guests.send(
            make_encounter(1),
            reason=EncounterInviteReason.CHANGED,
            guests=world.guests.guests(make_encounter(1)),
        )

        assert [
            (i.uid, i.end_time, i.organizer_name) for i in world.mailer.invites
        ] == [("CODE1@ludamus", START_TIME + ENCOUNTER_DEFAULT_DURATION, "Ola")]

    def test_an_invitee_without_an_account_is_mailed_unnamed(self):
        world = EncounterWorld(invitees={(1, "ola@example.com"): InviteeStatus.INVITED})

        world.guests.send(
            make_encounter(1),
            reason=EncounterInviteReason.CHANGED,
            guests=world.guests.guests(make_encounter(1)),
        )

        assert [(i.attendee_email, i.attendee_name) for i in world.mailer.invites] == [
            (CREATOR_EMAIL, ""),
            ("ola@example.com", ""),
        ]

    def test_a_deleted_creators_invitees_are_mailed_without_a_budget(self):
        world = EncounterWorld(users=[])
        invitee = Guest(
            email="ola@example.com",
            name="",
            partstat=PartStat.NEEDS_ACTION,
            invited_only=True,
        )

        world.guests.send(
            make_encounter(1), reason=EncounterInviteReason.INVITED, guests=[invitee]
        )

        assert world.mailer.sent == [(EncounterInviteReason.INVITED, "ola@example.com")]
        assert not world.invitees.mailings

    def test_a_week_old_account_has_the_smaller_mail_budget(self):
        fresh = make_user(date_joined=datetime.now(UTC) - timedelta(days=1))
        world = EncounterWorld(users=[fresh])
        invitees = [
            Guest(
                email=f"g{n}@example.com",
                name="",
                partstat=PartStat.NEEDS_ACTION,
                invited_only=True,
            )
            for n in range(CALENDAR_MAILS_PER_NEW_CREATOR_PER_DAY + 1)
        ]

        with pytest.raises(InviteLimitError):
            world.guests.send(
                make_encounter(1), reason=EncounterInviteReason.INVITED, guests=invitees
            )

        assert not world.mailer.sent
