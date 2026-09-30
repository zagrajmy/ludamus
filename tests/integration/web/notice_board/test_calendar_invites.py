import email.policy
import re
from datetime import UTC, datetime
from unittest.mock import patch

from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.links.absolute_url import absolute_url
from tests.integration.conftest import (
    EncounterFactory,
    EncounterRSVPFactory,
    UserFactory,
)


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
    # The SMTP backend serialises with the SMTP policy; that is what a
    # receiving calendar parses.
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


class TestOwnerChangesReachAttendees:
    def test_edit_mails_attendees_an_update(
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

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:edit", kwargs={"pk": encounter.pk}),
                data={
                    "title": "Moved game night",
                    "start_time": "2031-05-01T19:00",
                    "max_participants": 6,
                },
            )

        [message] = mailoutbox
        assert message.to == [attendee.email]
        ics, _mimetype = _calendar_part(message)
        assert "METHOD:REQUEST" in ics
        assert "SUMMARY:Moved game night" in ics

    def test_edit_without_calendar_change_mails_nobody(
        self,
        authenticated_client,
        user,
        sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        encounter = EncounterFactory(
            creator=user,
            sphere=sphere,
            start_time=datetime(2031, 5, 1, 17, 0, tzinfo=UTC),
            end_time=None,
        )
        EncounterRSVPFactory(encounter=encounter, user=UserFactory())

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:edit", kwargs={"pk": encounter.pk}),
                data={
                    "title": encounter.title,
                    "description": encounter.description,
                    "place": encounter.place,
                    "start_time": (
                        localtime(encounter.start_time).strftime("%Y-%m-%dT%H:%M")
                    ),
                    "max_participants": NEW_CAPACITY,
                },
            )

        encounter.refresh_from_db()
        assert encounter.max_participants == NEW_CAPACITY
        assert mailoutbox == []

    def test_delete_mails_attendees_a_cancel(
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

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(
                reverse("web:notice-board:delete", kwargs={"pk": encounter.pk})
            )

        [message] = mailoutbox
        assert message.to == [attendee.email]
        ics, _mimetype = _calendar_part(message)
        assert "METHOD:CANCEL" in ics
        assert f"UID:{encounter.share_code}@ludamus" in ics
