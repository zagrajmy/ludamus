from datetime import UTC, datetime

from ludamus.mills.crowd import EmailVerificationReminderService
from ludamus.pacts.crowd import VerificationRequestOutcome
from ludamus.specs.crowd import EMAIL_VERIFICATION_REMINDER_INTERVAL

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class FakeReminderRepo:
    def __init__(self, slugs=()):
        self._slugs = list(slugs)
        self.calls = []

    def list_due(self, *, now, interval):
        self.calls.append((now, interval))
        return self._slugs


class FakeVerification:
    def __init__(self, outcomes=None):
        self._outcomes = outcomes or {}
        self.requested = []

    def request_verification(self, user_slug):
        self.requested.append(user_slug)
        return self._outcomes.get(user_slug, VerificationRequestOutcome.SENT)


def _service(repo, verification=None):
    return EmailVerificationReminderService(
        reminders=repo, verification=verification or FakeVerification()
    )


class TestSendDueReminders:
    def test_routes_each_due_user_through_request_verification(self):
        repo = FakeReminderRepo(["a", "b"])
        verification = FakeVerification()
        service = _service(repo, verification)

        sent = service.send_due_reminders(now=NOW)

        assert verification.requested == ["a", "b"]
        assert sent == len(verification.requested)
        assert repo.calls == [(NOW, EMAIL_VERIFICATION_REMINDER_INTERVAL)]

    def test_counts_only_actually_sent(self):
        repo = FakeReminderRepo(["a", "b", "c"])
        verification = FakeVerification(
            {
                "b": VerificationRequestOutcome.THROTTLED,
                "c": VerificationRequestOutcome.NOT_NEEDED,
            }
        )
        service = _service(repo, verification)

        assert service.send_due_reminders(now=NOW) == 1

    def test_count_due_sends_nothing(self):
        due = ["a", "b"]
        repo = FakeReminderRepo(due)
        verification = FakeVerification()
        service = _service(repo, verification)

        assert service.count_due(now=NOW) == len(due)
        assert not verification.requested
