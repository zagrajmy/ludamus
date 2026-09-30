import re
from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY, patch

import pytest
from django.contrib.messages import constants
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.models import Encounter, EncounterInvitee, EncounterRSVP
from tests.integration.conftest import (
    EncounterFactory,
    EncounterInviteeFactory,
    EncounterRSVPFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.notice_board.calendar_mail import (
    MAX_ICS_LINE_OCTETS,
    calendar_part,
    rsvp,
    wire_calendar_lines,
)

NEW_CAPACITY = 12


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
        ics, mimetype = calendar_part(message)
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
            rsvp(authenticated_client, encounter)

        [message] = mailoutbox
        lines = wire_calendar_lines(message)
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
            rsvp(authenticated_client, encounter)

        [message] = mailoutbox
        ics, _mimetype = calendar_part(message)
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
            rsvp(authenticated_client, encounter)

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
        ics, mimetype = calendar_part(message)
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
        creator_ics, _mimetype = calendar_part(messages[user.email])
        assert "PARTSTAT=ACCEPTED" in creator_ics
        invitee_ics, _mimetype = calendar_part(messages["ala@example.com"])
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
        ics, _mimetype = calendar_part(messages[attendee.email])
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
        assert "METHOD:REQUEST" in calendar_part(messages["new@example.com"])[0]
        assert "METHOD:CANCEL" in calendar_part(messages["removed@example.com"])[0]

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
        ics, _mimetype = calendar_part(messages["ala@example.com"])
        assert "METHOD:CANCEL" in ics
        assert f"UID:{encounter.share_code}@ludamus" in ics


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
            rsvp(authenticated_client, encounter)

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
