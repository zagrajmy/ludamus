import email.policy
import re
from datetime import UTC, datetime
from email.message import EmailMessage
from http import HTTPStatus
from unittest.mock import ANY, patch

import pytest
from django.contrib.messages import constants
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.encounter_invites import SignedReplyAddress
from ludamus.links.db.django.models import Encounter, EncounterInvitee, EncounterRSVP
from ludamus.mills.encounter_calendar import encounter_calendar_uid
from tests.integration.conftest import (
    EncounterFactory,
    EncounterInviteeFactory,
    EncounterRSVPFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404


def _calendar_part(message):
    [(content, mimetype)] = [
        (content, mimetype)
        for content, mimetype in message.alternatives
        if mimetype.startswith("text/calendar")
    ]
    return content, mimetype


MAX_ICS_LINE_OCTETS = 75
NEW_CAPACITY = 12


def _wire_calendar_lines(message):
    # NOTE: prod's SMTP backend serialises with email.policy.SMTP; that is
    # what a receiving calendar parses.
    raw = message.message(policy=email.policy.SMTP).as_bytes()
    start = raw.index(b"BEGIN:VCALENDAR")
    end = raw.index(b"END:VCALENDAR") + len(b"END:VCALENDAR\r\n")
    return raw[start:end].split(b"\r\n")[:-1]


def _rsvp(client, encounter):
    return client.post(
        reverse(
            "web:notice-board:encounter-rsvp",
            kwargs={"share_code": encounter.share_code},
        )
    )


def _detail_url(encounter):
    return absolute_url(
        reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        ),
        domain=encounter.sphere.site.domain,
    )


class TestSignUpSendsInvite:
    def test_rsvp_mails_a_calendar_request(
        self,
        authenticated_client,
        encounter,
        user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse(
                    "web:notice-board:encounter-rsvp",
                    kwargs={"share_code": encounter.share_code},
                )
            )

        [message] = mailoutbox
        assert message.to == [user.email]
        ics, mimetype = _calendar_part(message)
        assert mimetype == "text/calendar; method=REQUEST; charset=utf-8"
        assert "METHOD:REQUEST" in ics
        assert f"UID:{encounter.share_code}@ludamus" in ics
        assert f"mailto:{user.email}" in ics.replace("\r\n ", "")
        assert "PARTSTAT=ACCEPTED" in ics
        assert _detail_url(encounter) in message.body

    def test_repeat_rsvp_sends_nothing(
        self,
        authenticated_client,
        encounter,
        user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        EncounterRSVPFactory(encounter=encounter, user=user)

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse(
                    "web:notice-board:encounter-rsvp",
                    kwargs={"share_code": encounter.share_code},
                )
            )

        assert mailoutbox == []

    def test_user_without_email_signs_up_without_mail(
        self,
        authenticated_client,
        encounter,
        user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        user.email = ""
        user.save()

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse(
                    "web:notice-board:encounter-rsvp",
                    kwargs={"share_code": encounter.share_code},
                )
            )

        assert encounter.rsvps.filter(user=user).exists()
        assert mailoutbox == []

    def test_multiline_description_stays_valid_icalendar_on_the_wire(
        self,
        authenticated_client,
        sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        encounter = EncounterFactory(
            sphere=sphere,
            description="Zabierz kości\r\ni przekąski; " + "długi opis " * 20,
        )

        with django_capture_on_commit_callbacks(execute=True):
            _rsvp(authenticated_client, encounter)

        [message] = mailoutbox
        lines = _wire_calendar_lines(message)
        content_line = re.compile(rb"^[A-Z-]+[;:]")
        assert all(content_line.match(line) or line.startswith(b" ") for line in lines)
        assert all(len(line) <= MAX_ICS_LINE_OCTETS for line in lines)
        unfolded = b"\r\n".join(lines).replace(b"\r\n ", b"").decode()
        assert "DESCRIPTION:Zabierz kości\\ni przekąski\\; długi" in unfolded

    def test_attendee_without_name_is_named_by_email(
        self,
        authenticated_client,
        encounter,
        user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        user.name = ""
        user.save()

        with django_capture_on_commit_callbacks(execute=True):
            _rsvp(authenticated_client, encounter)

        [message] = mailoutbox
        ics, _mimetype = _calendar_part(message)
        assert f'ATTENDEE;CN="{user.email}"' in ics

    def test_failed_delivery_keeps_the_signup_and_is_logged(
        self,
        authenticated_client,
        encounter,
        user,
        caplog,
        django_capture_on_commit_callbacks,
    ):
        with (
            patch(
                "django.core.mail.backends.locmem.EmailBackend.send_messages",
                side_effect=ConnectionRefusedError,
            ),
            caplog.at_level(
                "ERROR", logger="ludamus.links.db.django.encounter_invites"
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            _rsvp(authenticated_client, encounter)

        assert encounter.rsvps.filter(user=user).exists()
        assert f"Encounter {encounter.share_code}: joined invites not delivered" in (
            caplog.text
        )


class TestLeavingCancelsInvite:
    def test_cancel_rsvp_mails_a_calendar_cancel(
        self,
        authenticated_client,
        encounter,
        user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        EncounterRSVPFactory(encounter=encounter, user=user)

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse(
                    "web:notice-board:encounter-cancel-rsvp",
                    kwargs={"share_code": encounter.share_code},
                )
            )

        [message] = mailoutbox
        assert message.to == [user.email]
        ics, mimetype = _calendar_part(message)
        assert mimetype == "text/calendar; method=CANCEL; charset=utf-8"
        assert "STATUS:CANCELLED" in ics

    def test_cancel_without_rsvp_sends_nothing(
        self,
        authenticated_client,
        encounter,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse(
                    "web:notice-board:encounter-cancel-rsvp",
                    kwargs={"share_code": encounter.share_code},
                )
            )

        assert mailoutbox == []


def _by_recipient(mailoutbox):
    return {message.to[0]: message for message in mailoutbox}


def _edit_data(encounter, **overrides):
    return {
        "title": encounter.title,
        "description": encounter.description,
        "place": encounter.place,
        "start_time": localtime(encounter.start_time).strftime("%Y-%m-%dT%H:%M"),
        "max_participants": encounter.max_participants,
    } | overrides


def _minute_encounter(**kwargs):
    # NOTE: the form's datetime-local drops seconds; a whole minute makes an
    # unchanged form post an unchanged start.
    return EncounterFactory(
        start_time=datetime(2031, 5, 1, 17, 0, tzinfo=UTC), end_time=None, **kwargs
    )


class TestCreatingInvitesEveryone:
    def test_creator_and_invitees_get_invites(
        self, authenticated_client, user, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:create"),
                data={
                    "title": "Board game night",
                    "start_time": "2031-05-01T19:00",
                    "invitees": "Ala@example.com, bob@example.com\nala@example.com",
                },
            )

        encounter = Encounter.objects.get(title="Board game night")
        assert sorted(encounter.invitees.values_list("email", flat=True)) == [
            "ala@example.com",
            "bob@example.com",
        ]
        messages = _by_recipient(mailoutbox)
        assert sorted(messages) == sorted(
            [user.email, "ala@example.com", "bob@example.com"]
        )
        creator_ics, _mimetype = _calendar_part(messages[user.email])
        assert "PARTSTAT=ACCEPTED" in creator_ics
        invitee_ics, _mimetype = _calendar_part(messages["ala@example.com"])
        assert "METHOD:REQUEST" in invitee_ics
        assert "PARTSTAT=NEEDS-ACTION" in invitee_ics

    def test_invalid_address_blocks_the_form(
        self, authenticated_client, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(
                reverse("web:notice-board:create"),
                data={
                    "title": "Board game night",
                    "start_time": "2031-05-01T19:00",
                    "invitees": "ala@example.com, not-an-address",
                },
            )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert not Encounter.objects.filter(title="Board game night").exists()
        assert mailoutbox == []


class TestOwnerChangesReachGuests:
    def test_edit_mails_every_guest_an_update(
        self,
        authenticated_client,
        user,
        sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        encounter = _minute_encounter(creator=user, sphere=sphere)
        attendee = UserFactory()
        EncounterRSVPFactory(encounter=encounter, user=attendee)
        EncounterInviteeFactory(encounter=encounter, email="ala@example.com")
        EncounterInviteeFactory(
            encounter=encounter,
            email="gone@example.com",
            status=EncounterInvitee.Status.DECLINED,
        )

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:edit", kwargs={"pk": encounter.pk}),
                data=_edit_data(
                    encounter,
                    title="Moved game night",
                    invitees="ala@example.com\ngone@example.com",
                ),
            )

        messages = _by_recipient(mailoutbox)
        assert sorted(messages) == sorted(
            [user.email, attendee.email, "ala@example.com"]
        )
        ics, _mimetype = _calendar_part(messages[attendee.email])
        assert "METHOD:REQUEST" in ics
        assert "SUMMARY:Moved game night" in ics

    def test_edit_invites_the_added_and_cancels_the_removed(
        self,
        authenticated_client,
        user,
        sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        encounter = _minute_encounter(creator=user, sphere=sphere)
        EncounterInviteeFactory(encounter=encounter, email="stays@example.com")
        EncounterInviteeFactory(encounter=encounter, email="removed@example.com")
        signed_up = UserFactory(email="signed@example.com")
        EncounterInviteeFactory(encounter=encounter, email=signed_up.email)
        EncounterRSVPFactory(encounter=encounter, user=signed_up)

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:edit", kwargs={"pk": encounter.pk}),
                data=_edit_data(
                    encounter, invitees="stays@example.com, new@example.com"
                ),
            )

        on_list = encounter.invitees.exclude(status=EncounterInvitee.Status.REMOVED)
        assert sorted(on_list.values_list("email", flat=True)) == [
            "new@example.com",
            "stays@example.com",
        ]
        messages = _by_recipient(mailoutbox)
        assert sorted(messages) == ["new@example.com", "removed@example.com"]
        assert "METHOD:REQUEST" in _calendar_part(messages["new@example.com"])[0]
        assert "METHOD:CANCEL" in _calendar_part(messages["removed@example.com"])[0]

    def test_edit_without_calendar_change_mails_nobody(
        self,
        authenticated_client,
        user,
        sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        encounter = _minute_encounter(creator=user, sphere=sphere)
        EncounterRSVPFactory(encounter=encounter, user=UserFactory())

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:edit", kwargs={"pk": encounter.pk}),
                data=_edit_data(encounter, max_participants=NEW_CAPACITY),
            )

        encounter.refresh_from_db()
        assert encounter.max_participants == NEW_CAPACITY
        assert mailoutbox == []

    def test_delete_cancels_every_guest(
        self,
        authenticated_client,
        user,
        sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        encounter = EncounterFactory(creator=user, sphere=sphere)
        attendee = UserFactory()
        EncounterRSVPFactory(encounter=encounter, user=attendee)
        EncounterInviteeFactory(encounter=encounter, email="ala@example.com")

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:delete", kwargs={"pk": encounter.pk})
            )

        messages = _by_recipient(mailoutbox)
        assert sorted(messages) == sorted(
            [user.email, attendee.email, "ala@example.com"]
        )
        ics, _mimetype = _calendar_part(messages["ala@example.com"])
        assert "METHOD:CANCEL" in ics
        assert f"UID:{encounter.share_code}@ludamus" in ics


REPLY_EMAIL = "rsvp@replies.example.com"
WEBHOOK_SECRET = "s3cret"


def _reply_mail(*, uid, attendee, partstat):
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "METHOD:REPLY",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"ATTENDEE;PARTSTAT={partstat}:mailto:{attendee}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    message = EmailMessage()
    message["From"] = attendee
    message["Subject"] = "Accepted"
    message.set_content("Accepted")
    message.add_alternative(ics, subtype="calendar", params={"method": "REPLY"})
    return message.as_bytes()


@pytest.fixture(name="reply_sync")
def reply_sync_fixture(settings):
    settings.ENCOUNTER_REPLY_EMAIL = REPLY_EMAIL
    settings.ENCOUNTER_REPLY_WEBHOOK_SECRET = WEBHOOK_SECRET


@pytest.mark.usefixtures("reply_sync")
class TestCalendarReplies:
    @staticmethod
    def _post(client, body, *, to, secret=WEBHOOK_SECRET):
        return client.post(
            reverse("web:calendar-replies"),
            data=body,
            content_type="message/rfc822",
            headers={"authorization": f"Bearer {secret}", "x-envelope-to": to},
        )

    @staticmethod
    def _address(encounter, attendee_email):
        return SignedReplyAddress.address_for(
            uid=encounter_calendar_uid(encounter.share_code),
            attendee_email=attendee_email,
        )

    def test_invite_asks_for_a_reply_to_a_signed_address(
        self,
        authenticated_client,
        encounter,
        user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _rsvp(authenticated_client, encounter)

        ics = _calendar_part(mailoutbox[0])[0].replace("\r\n ", "")
        assert f"mailto:{self._address(encounter, user.email)}" in ics
        assert "RSVP=TRUE" in ics

    def test_accepting_signs_the_account_up(
        self, client, encounter, mailoutbox, django_capture_on_commit_callbacks
    ):
        guest = UserFactory(email="guest@example.com")
        EncounterInviteeFactory(encounter=encounter, email=guest.email)

        with django_capture_on_commit_callbacks(execute=True):
            response = self._post(
                client,
                _reply_mail(
                    uid=encounter_calendar_uid(encounter.share_code),
                    attendee="Guest@Example.com",
                    partstat="ACCEPTED",
                ),
                to=self._address(encounter, guest.email),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "accepted"})
        assert encounter.rsvps.filter(user=guest, ip_address=None).exists()
        assert encounter.invitees.get(email=guest.email).status == "accepted"
        assert mailoutbox == []

    def test_accepting_a_full_encounter_is_cancelled_back(
        self, client, sphere, mailoutbox, django_capture_on_commit_callbacks
    ):
        encounter = EncounterFactory(sphere=sphere, max_participants=1)
        EncounterRSVPFactory(encounter=encounter)
        guest = UserFactory(email="late@example.com")
        EncounterInviteeFactory(encounter=encounter, email=guest.email)

        with django_capture_on_commit_callbacks(execute=True):
            response = self._post(
                client,
                _reply_mail(
                    uid=encounter_calendar_uid(encounter.share_code),
                    attendee=guest.email,
                    partstat="ACCEPTED",
                ),
                to=self._address(encounter, guest.email),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "full"})
        assert not encounter.rsvps.filter(user=guest).exists()
        [message] = mailoutbox
        assert message.to == [guest.email]
        assert "METHOD:CANCEL" in _calendar_part(message)[0]

    def test_declining_removes_the_signup(self, client, encounter):
        guest = UserFactory(email="guest@example.com")
        EncounterRSVPFactory(encounter=encounter, user=guest)

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee=guest.email,
                partstat="DECLINED",
            ),
            to=self._address(encounter, guest.email),
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "declined"})
        assert not encounter.rsvps.filter(user=guest).exists()

    def test_guest_without_account_is_marked_accepted(self, client, encounter):
        EncounterInviteeFactory(encounter=encounter, email="friend@example.com")

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="friend@example.com",
                partstat="ACCEPTED",
            ),
            to=self._address(encounter, "friend@example.com"),
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "accepted"})
        assert encounter.invitees.get(email="friend@example.com").status == "accepted"
        assert not encounter.rsvps.exists()

    def test_reply_for_someone_else_is_forged(self, client, encounter):
        victim = UserFactory(email="victim@example.com")
        EncounterRSVPFactory(encounter=encounter, user=victim)

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee=victim.email,
                partstat="DECLINED",
            ),
            to=self._address(encounter, "attacker@example.com"),
        )

        assert_response(response, HTTPStatus.FORBIDDEN, json={"outcome": "forged"})
        assert encounter.rsvps.filter(user=victim).exists()

    def test_wrong_secret_is_unauthorized(self, client, encounter):
        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="a@example.com",
                partstat="ACCEPTED",
            ),
            to=self._address(encounter, "a@example.com"),
            secret="wrong",
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_plain_mail_is_unprocessable(self, client, encounter):
        message = EmailMessage()
        message.set_content("Hi, can I bring a friend?")

        response = self._post(
            client, message.as_bytes(), to=self._address(encounter, "a@example.com")
        )

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "Not a calendar reply."},
        )

    def test_webhook_is_closed_without_a_secret(self, client, encounter, settings):
        settings.ENCOUNTER_REPLY_WEBHOOK_SECRET = ""

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="a@example.com",
                partstat="ACCEPTED",
            ),
            to=self._address(encounter, "a@example.com"),
            secret="",
        )

        assert_response_404(response)

    def test_guest_without_account_accepting_a_full_encounter_is_cancelled_back(
        self, client, sphere, mailoutbox, django_capture_on_commit_callbacks
    ):
        encounter = EncounterFactory(sphere=sphere, max_participants=1)
        EncounterRSVPFactory(encounter=encounter)
        EncounterInviteeFactory(encounter=encounter, email="friend@example.com")

        with django_capture_on_commit_callbacks(execute=True):
            response = self._post(
                client,
                _reply_mail(
                    uid=encounter_calendar_uid(encounter.share_code),
                    attendee="friend@example.com",
                    partstat="ACCEPTED",
                ),
                to=self._address(encounter, "friend@example.com"),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "full"})
        assert encounter.invitees.get(email="friend@example.com").status == "invited"
        [message] = mailoutbox
        assert message.to == ["friend@example.com"]
        assert "METHOD:CANCEL" in _calendar_part(message)[0]

    def test_account_that_was_never_invited_cannot_accept(self, client, encounter):
        stranger = UserFactory(email="stranger@example.com")

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee=stranger.email,
                partstat="ACCEPTED",
            ),
            to=self._address(encounter, stranger.email),
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ignored"})
        assert not encounter.rsvps.exists()

    def test_reply_for_a_deleted_encounter_is_ignored(self, client, encounter):
        uid = encounter_calendar_uid(encounter.share_code)
        address = self._address(encounter, "a@example.com")
        encounter.delete()

        response = self._post(
            client,
            _reply_mail(uid=uid, attendee="a@example.com", partstat="DECLINED"),
            to=address,
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ignored"})

    def test_latin1_calendar_attachment_is_read(self, client, encounter):
        EncounterInviteeFactory(encounter=encounter, email="zosia@example.com")
        ics = (
            "BEGIN:VCALENDAR\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
            f"UID:{encounter_calendar_uid(encounter.share_code)}\r\n"
            'ATTENDEE;CN="Zo\u015bka \u00d3";PARTSTAT=DECLINED'
            ":mailto:zosia@example.com\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        message = EmailMessage()
        message.set_content("Declined")
        message.add_attachment(
            ics.encode("latin-1", errors="replace"),
            maintype="application",
            subtype="ics",
            filename="reply.ics",
        )
        message.get_payload()[1].set_param("charset", "iso-8859-1")

        response = self._post(
            client, message.as_bytes(), to=self._address(encounter, "zosia@example.com")
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "declined"})

    def test_creator_is_not_asked_to_reply(
        self, authenticated_client, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:create"),
                data={"title": "Solo prep", "start_time": "2031-05-01T19:00"},
            )

        [message] = mailoutbox
        assert "RSVP=FALSE" in _calendar_part(message)[0].replace("\r\n ", "")

    def test_a_tentative_answer_changes_nothing(self, client, encounter):
        EncounterInviteeFactory(encounter=encounter, email="maybe@example.com")

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="maybe@example.com",
                partstat="TENTATIVE",
            ),
            to=self._address(encounter, "maybe@example.com"),
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ignored"})
        assert encounter.invitees.get(email="maybe@example.com").status == "invited"

    def test_an_answer_we_do_not_know_is_unprocessable(self, client, encounter):
        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="a@example.com",
                partstat="DELEGATED",
            ),
            to=self._address(encounter, "a@example.com"),
        )

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "Not a calendar reply."},
        )

    def test_creator_answering_their_own_invite_is_ignored(self, client, encounter):
        creator = encounter.creator

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee=creator.email,
                partstat="ACCEPTED",
            ),
            to=self._address(encounter, creator.email),
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ignored"})
        assert not encounter.rsvps.exists()

    def test_declining_with_nothing_to_undo_is_ignored(self, client, encounter):
        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="nobody@example.com",
                partstat="DECLINED",
            ),
            to=self._address(encounter, "nobody@example.com"),
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ignored"})

    def test_a_forwarded_request_is_not_a_reply(self, client, encounter):
        body = _reply_mail(
            uid=encounter_calendar_uid(encounter.share_code),
            attendee="a@example.com",
            partstat="ACCEPTED",
        ).replace(b"METHOD:REPLY", b"METHOD:REQUEST")

        response = self._post(
            client, body, to=self._address(encounter, "a@example.com")
        )

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "Not a calendar reply."},
        )

    def test_a_repeated_acceptance_keeps_the_spot_quietly(
        self, client, sphere, mailoutbox, django_capture_on_commit_callbacks
    ):
        encounter = EncounterFactory(sphere=sphere, max_participants=1)
        EncounterInviteeFactory(
            encounter=encounter,
            email="friend@example.com",
            status=EncounterInvitee.Status.ACCEPTED,
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = self._post(
                client,
                _reply_mail(
                    uid=encounter_calendar_uid(encounter.share_code),
                    attendee="friend@example.com",
                    partstat="ACCEPTED",
                ),
                to=self._address(encounter, "friend@example.com"),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ignored"})
        assert encounter.invitees.get(email="friend@example.com").status == "accepted"
        assert mailoutbox == []


class TestAcceptedGuestsHoldSpots:
    def test_guest_who_accepted_then_made_an_account_keeps_the_spot(
        self, authenticated_client, sphere, user
    ):
        encounter = EncounterFactory(sphere=sphere, max_participants=1)
        late_account = UserFactory(email="friend@example.com")
        EncounterInviteeFactory(
            encounter=encounter,
            email=late_account.email,
            status=EncounterInvitee.Status.ACCEPTED,
        )

        response = _rsvp(authenticated_client, encounter)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.ERROR, "This encounter is full."),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        assert not encounter.rsvps.filter(user=user).exists()


class TestInviteLimits:
    def test_deleting_and_recreating_does_not_reset_the_daily_limit(
        self, authenticated_client, mailoutbox, django_capture_on_commit_callbacks
    ):
        for batch in ("a", "b"):
            emails = ", ".join(f"{batch}{n}@example.com" for n in range(50))
            with django_capture_on_commit_callbacks(execute=True):
                authenticated_client.post(
                    reverse("web:notice-board:create"),
                    data={
                        "title": f"Night {batch}",
                        "start_time": "2031-05-01T19:00",
                        "invitees": emails,
                    },
                )
            encounter = Encounter.objects.get(title=f"Night {batch}")
            with django_capture_on_commit_callbacks(execute=True):
                authenticated_client.post(
                    reverse("web:notice-board:delete", kwargs={"pk": encounter.pk})
                )
        mailoutbox.clear()

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(
                reverse("web:notice-board:create"),
                data={
                    "title": "Night c",
                    "start_time": "2031-05-01T19:00",
                    "invitees": "one-more@example.com",
                },
            )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=((constants.SUCCESS, "Encounter deleted."),) * 2,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert not Encounter.objects.filter(title="Night c").exists()
        assert mailoutbox == []

    def test_more_than_fifty_addresses_at_once_are_refused(
        self, authenticated_client, mailoutbox
    ):
        response = authenticated_client.post(
            reverse("web:notice-board:create"),
            data={
                "title": "Crowd night",
                "start_time": "2031-05-01T19:00",
                "invitees": ", ".join(f"p{n}@example.com" for n in range(51)),
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert not Encounter.objects.filter(title="Crowd night").exists()
        assert mailoutbox == []

    def test_swapping_the_list_counts_toward_the_daily_limit(
        self,
        authenticated_client,
        user,
        sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        encounter = _minute_encounter(creator=user, sphere=sphere)
        url = reverse("web:notice-board:edit", kwargs={"pk": encounter.pk})
        for batch in ("a", "b"):
            emails = ", ".join(f"{batch}{n}@example.com" for n in range(50))
            with django_capture_on_commit_callbacks(execute=True):
                authenticated_client.post(
                    url, data=_edit_data(encounter, invitees=emails)
                )
        mailoutbox.clear()

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(
                url, data=_edit_data(encounter, invitees="one-more@example.com")
            )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=((constants.SUCCESS, "Encounter updated."),) * 2,
            context_data={"form": ANY, "encounter": ANY},
            template_name="notice_board/edit.html",
        )
        assert sorted(encounter.invitees.values_list("status", flat=True)) == (
            ["invited"] * 50 + ["removed"] * 50
        )
        assert mailoutbox == []


class TestSignupRollsBackAsOne:
    def test_failure_after_the_signup_leaves_no_signup_and_no_mail(
        self,
        authenticated_client,
        encounter,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with (
            patch(
                "ludamus.links.db.django.repositories.notice_board."
                "EncounterInviteeRepository.set_status",
                side_effect=RuntimeError,
            ),
            pytest.raises(RuntimeError),
            django_capture_on_commit_callbacks(execute=True),
        ):
            _rsvp(authenticated_client, encounter)

        assert not EncounterRSVP.objects.filter(encounter=encounter).exists()
        assert mailoutbox == []


class TestForeignEncounter:
    def test_editing_someone_elses_encounter_touches_no_invitees(
        self, authenticated_client, sphere, mailoutbox
    ):
        encounter = EncounterFactory(sphere=sphere)
        EncounterInviteeFactory(encounter=encounter, email="ala@example.com")

        response = authenticated_client.post(
            reverse("web:notice-board:edit", kwargs={"pk": encounter.pk}),
            data=_edit_data(encounter, invitees="mallory@example.com"),
        )

        assert_response_404(response)
        assert list(encounter.invitees.values_list("email", flat=True)) == [
            "ala@example.com"
        ]
        assert mailoutbox == []
