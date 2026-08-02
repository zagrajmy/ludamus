from datetime import UTC, datetime, timedelta

from django.core.management import call_command
from django.urls import reverse

from ludamus.links.db.django.models import Notification
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import EventFactory, UserFactory


def _event_starting_in(sphere, delta):
    start = datetime.now(UTC) + delta
    return EventFactory(
        sphere=sphere,
        start_time=start,
        end_time=start + timedelta(hours=8),
        publication_time=datetime.now(UTC) - timedelta(days=14),
    )


class TestSendPrintablesReminders:
    def test_reminds_organizers_within_lead_time(
        self, sphere, active_user, mailoutbox, django_capture_on_commit_callbacks
    ):
        sphere.managers.add(active_user)
        event = _event_starting_in(sphere, timedelta(days=1))

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_printables_reminders")

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert email.to == [active_user.email]
        assert event.name in email.subject
        path = reverse("panel:print-materials", kwargs={"slug": event.slug})
        assert f"https://{sphere.site.domain}{path}" in email.body
        notification = Notification.objects.get(recipient=active_user)
        assert notification.kind == NotificationKind.PRINTABLES_READY.value
        event.refresh_from_db()
        assert event.printables_reminder_sent_at is not None

    def test_skips_event_already_printed(
        self, sphere, active_user, mailoutbox, django_capture_on_commit_callbacks
    ):
        sphere.managers.add(active_user)
        event = _event_starting_in(sphere, timedelta(days=1))
        event.printables_last_printed_at = datetime.now(UTC)
        event.save(update_fields=["printables_last_printed_at"])

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_printables_reminders")

        assert mailoutbox == []
        event.refresh_from_db()
        assert event.printables_reminder_sent_at is None

    def test_skips_event_already_reminded(
        self, sphere, active_user, mailoutbox, django_capture_on_commit_callbacks
    ):
        sphere.managers.add(active_user)
        event = _event_starting_in(sphere, timedelta(days=1))
        event.printables_reminder_sent_at = datetime.now(UTC)
        event.save(update_fields=["printables_reminder_sent_at"])

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_printables_reminders")

        assert mailoutbox == []

    def test_skips_event_outside_lead_time(
        self, sphere, active_user, mailoutbox, django_capture_on_commit_callbacks
    ):
        sphere.managers.add(active_user)
        _event_starting_in(sphere, timedelta(days=5))

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_printables_reminders")

        assert mailoutbox == []

    def test_skips_event_that_already_started(
        self, sphere, active_user, mailoutbox, django_capture_on_commit_callbacks
    ):
        sphere.managers.add(active_user)
        _event_starting_in(sphere, timedelta(hours=-1))

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_printables_reminders")

        assert mailoutbox == []

    def test_skips_managers_without_email_and_leaves_event_unmarked(
        self, sphere, mailoutbox, django_capture_on_commit_callbacks
    ):
        sphere.managers.add(UserFactory(username="no-email", email=""))
        event = _event_starting_in(sphere, timedelta(days=1))

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_printables_reminders")

        assert mailoutbox == []
        event.refresh_from_db()
        assert event.printables_reminder_sent_at is None
