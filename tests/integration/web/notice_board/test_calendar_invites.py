from django.urls import reverse

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
