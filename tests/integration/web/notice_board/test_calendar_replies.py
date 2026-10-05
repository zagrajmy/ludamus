from email.message import EmailMessage
from http import HTTPStatus

import pytest
from django.contrib.messages import constants
from django.urls import reverse

from ludamus.links.db.django.encounter_invites import SignedReplyAddress
from ludamus.links.db.django.models import EncounterInvitee
from ludamus.mills.encounter_calendar import encounter_calendar_uid
from tests.integration.conftest import (
    EncounterFactory,
    EncounterInviteeFactory,
    EncounterRSVPFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.notice_board.calendar_mail import calendar_part, rsvp

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
            rsvp(authenticated_client, encounter)

        ics = calendar_part(mailoutbox[0])[0].replace("\r\n ", "")
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
        assert "METHOD:CANCEL" in calendar_part(message)[0]

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

    def test_a_reply_signed_before_a_key_rotation_still_counts(
        self, client, encounter, settings
    ):
        EncounterInviteeFactory(encounter=encounter, email="friend@example.com")
        address = self._address(encounter, "friend@example.com")
        settings.SECRET_KEY_FALLBACKS = [settings.SECRET_KEY]
        settings.SECRET_KEY = "rotated-" + settings.SECRET_KEY

        response = self._post(
            client,
            _reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="friend@example.com",
                partstat="ACCEPTED",
            ),
            to=address,
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "accepted"})
        assert encounter.invitees.get(email="friend@example.com").status == "accepted"

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
        assert "METHOD:CANCEL" in calendar_part(message)[0]

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
        assert "RSVP=FALSE" in calendar_part(message)[0].replace("\r\n ", "")

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

        response = rsvp(authenticated_client, encounter)

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


@pytest.mark.usefixtures("reply_sync")
class TestRepliesRespectThePolicy:
    def test_accepting_after_encounters_were_turned_off_signs_nobody_up(
        self, client, sphere, encounter
    ):
        guest = UserFactory(email="guest@example.com")
        EncounterInviteeFactory(encounter=encounter, email=guest.email)
        sphere.encounters_policy = "none"
        sphere.save()

        response = client.post(
            reverse("web:calendar-replies"),
            data=_reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee=guest.email,
                partstat="ACCEPTED",
            ),
            content_type="message/rfc822",
            headers={
                "authorization": f"Bearer {WEBHOOK_SECRET}",
                "x-envelope-to": SignedReplyAddress.address_for(
                    uid=encounter_calendar_uid(encounter.share_code),
                    attendee_email=guest.email,
                ),
            },
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ignored"})
        assert not encounter.rsvps.exists()

    def test_a_message_over_the_upload_limit_is_unprocessable(
        self, client, encounter, settings
    ):
        settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 100

        response = client.post(
            reverse("web:calendar-replies"),
            data=_reply_mail(
                uid=encounter_calendar_uid(encounter.share_code),
                attendee="a@example.com",
                partstat="ACCEPTED",
            ),
            content_type="message/rfc822",
            headers={
                "authorization": f"Bearer {WEBHOOK_SECRET}",
                "x-envelope-to": "rsvp@replies.example.com",
            },
        )

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "Message too large."},
        )
