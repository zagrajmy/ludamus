from datetime import UTC, datetime, timedelta
from io import StringIO

from django.core.management import call_command

from ludamus.links.db.django.models import Notification
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import UserFactory


def _unverified_user(**overrides):
    return UserFactory(email_verified=False, **overrides)


class TestSendVerificationReminders:
    def test_sends_fresh_link_to_due_user(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        user = _unverified_user()

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_verification_reminders")

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert email.to == [user.email]
        assert "/crowd/email/link/" in email.body
        notification = Notification.objects.get(recipient=user)
        assert notification.kind == NotificationKind.EMAIL_VERIFICATION.value
        user.refresh_from_db()
        assert user.email_verification_sent_at is not None

    def test_skips_recently_mailed_user(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        _unverified_user(email_verification_sent_at=datetime.now(UTC))

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_verification_reminders")

        assert mailoutbox == []

    def test_renags_after_the_interval(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        _unverified_user(
            email_verification_sent_at=datetime.now(UTC) - timedelta(days=8)
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_verification_reminders")

        assert len(mailoutbox) == 1

    def test_nags_a_user_whose_only_address_is_pending(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        user = _unverified_user(email="", pending_email="new@example.com")

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_verification_reminders")

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["new@example.com"]
        assert Notification.objects.filter(recipient=user).exists()

    def test_skips_verified_and_blank_addresses(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        UserFactory(email_verified=True)
        _unverified_user(email="")

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_verification_reminders")

        assert mailoutbox == []
        assert not Notification.objects.exists()

    def test_dry_run_counts_and_sends_nothing(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        _unverified_user()
        out = StringIO()

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_verification_reminders", "--dry-run", stdout=out)

        assert "1 user(s)" in out.getvalue()
        assert mailoutbox == []
        assert not Notification.objects.exists()
