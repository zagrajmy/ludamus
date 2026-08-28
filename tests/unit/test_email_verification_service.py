from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from ludamus.mills.crowd import EmailVerificationService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    ChangeRequestOutcome,
    EmailTokenPayload,
    EmailVerificationAction,
    RedeemOutcome,
    VerificationRequestOutcome,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.specs.crowd import EMAIL_VERIFICATION_REMINDER_INTERVAL
from tests.unit.factories import user_dto

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def atomic(self):
        return _atomic()

    def savepoint(self):
        return _atomic()


class FakeUsers:
    def __init__(self, *, users=(), existing_emails=(), constraint_on_email=None):
        self._users = list(users)
        self._existing_emails = set(existing_emails)
        self._constraint_on_email = constraint_on_email
        self.updated = []

    def read(self, slug):
        for user in self._users:
            if user.slug == slug:
                return user
        raise NotFoundError

    def read_by_id(self, pk):
        for user in self._users:
            if user.pk == pk:
                return user
        raise NotFoundError

    def update(self, user_slug, user_data):
        if self._constraint_on_email and (
            user_data.get("email") == self._constraint_on_email
        ):
            raise DatabaseConstraintError("duplicate email")
        self.updated.append((user_slug, user_data))
        for index, user in enumerate(self._users):
            if user.slug == user_slug:
                self._users[index] = user.model_copy(update=dict(user_data))

    def email_unavailable(self, *, email, now, exclude_slug=None):
        _ = (now, exclude_slug)
        return email in self._existing_emails


class FakeCodec:
    def __init__(self):
        self.minted = []

    def dumps(self, payload):
        self.minted.append(payload)
        return f"{payload.act.value}|{payload.uid}|{payload.addr}"

    @staticmethod
    def loads(token):
        try:
            act, uid, addr = token.split("|")
            return EmailTokenPayload(
                act=EmailVerificationAction(act), uid=int(uid), addr=addr
            )
        except ValueError:
            return None


class FakeReminders:
    def __init__(self, due=()):
        self._due = list(due)
        self.calls = []

    def count_due(self, *, now, interval):
        self.calls.append((now, interval))
        return len(self._due)

    def list_due(self, *, now, interval):
        self.calls.append((now, interval))
        return self._due


class FakeNotifier:
    def __init__(self):
        self.verifications = []
        self.change_requests = []
        self.change_completions = []

    def notify_email_verification(self, notification):
        self.verifications.append(notification)

    def notify_email_change_requested(self, notification):
        self.change_requests.append(notification)

    def notify_email_change_completed(self, notification):
        self.change_completions.append(notification)


def _service(users, *, codec=None, notifier=None, reminders=None):
    return EmailVerificationService(
        transaction=FakeTransaction(),
        users=users,
        reminders=reminders or FakeReminders(),
        tokens=codec or FakeCodec(),
        notifier=notifier or FakeNotifier(),
    )


def _user(**overrides):
    return user_dto(**{"slug": "auth0user", "pk": 1, **overrides})


def _token(act, addr, uid=1):
    return f"{act.value}|{uid}|{addr}"


class TestRequestVerification:
    def test_sends_link_to_unverified_address(self):
        users = FakeUsers(users=[_user(email="mine@example.com")])
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        outcome = service.request_verification("auth0user")

        assert outcome == VerificationRequestOutcome.SENT
        assert len(notifier.verifications) == 1
        assert notifier.verifications[0].recipient_email == "mine@example.com"
        assert users.updated[0][1].keys() == {"email_verification_sent_at"}

    def test_pending_change_outranks_current_address(self):
        users = FakeUsers(
            users=[_user(email="old@example.com", pending_email="new@example.com")]
        )
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        outcome = service.request_verification("auth0user")

        assert outcome == VerificationRequestOutcome.SENT
        assert notifier.verifications[0].recipient_email == "new@example.com"

    def test_verified_address_needs_nothing(self):
        users = FakeUsers(users=[_user(email="mine@example.com", email_verified=True)])
        service = _service(users)

        assert (
            service.request_verification("auth0user")
            == VerificationRequestOutcome.NOT_NEEDED
        )

    def test_no_address_needs_nothing(self):
        users = FakeUsers(users=[_user(email="")])
        service = _service(users)

        assert (
            service.request_verification("auth0user")
            == VerificationRequestOutcome.NOT_NEEDED
        )

    def test_recent_send_is_throttled(self):
        users = FakeUsers(
            users=[
                _user(
                    email="mine@example.com",
                    email_verification_sent_at=datetime.now(UTC),
                )
            ]
        )
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        outcome = service.request_verification("auth0user")

        assert outcome == VerificationRequestOutcome.THROTTLED
        assert not notifier.verifications
        assert not users.updated

    def test_stale_send_is_not_throttled(self):
        users = FakeUsers(
            users=[
                _user(
                    email="mine@example.com",
                    email_verification_sent_at=datetime.now(UTC) - timedelta(hours=1),
                )
            ]
        )
        service = _service(users)

        assert (
            service.request_verification("auth0user") == VerificationRequestOutcome.SENT
        )


class TestSendDueReminders:
    def test_mails_every_due_row_without_re_reading_it(self):
        due = [
            _user(slug="a", pk=1, email="a@example.com"),
            _user(slug="b", pk=2, email="", pending_email="b@example.com"),
        ]
        reminders = FakeReminders(due)
        notifier = FakeNotifier()
        service = _service(FakeUsers(), notifier=notifier, reminders=reminders)

        sent = service.send_due_reminders(now=NOW)

        assert sent == len(due)
        assert [n.recipient_email for n in notifier.verifications] == [
            "a@example.com",
            "b@example.com",
        ]
        assert reminders.calls == [(NOW, EMAIL_VERIFICATION_REMINDER_INTERVAL)]

    def test_counts_only_rows_that_were_mailed(self):
        due = [
            _user(slug="a", pk=1, email="a@example.com"),
            _user(
                slug="b", pk=2, email="b@example.com", email_verification_sent_at=NOW
            ),
            _user(slug="c", pk=3, email="", pending_email=""),
        ]
        service = _service(FakeUsers(), reminders=FakeReminders(due))

        assert service.send_due_reminders(now=NOW) == 1

    def test_count_due_asks_the_repository_and_mails_nothing(self):
        notifier = FakeNotifier()
        reminders = FakeReminders([_user(slug="a", pk=1, email="a@example.com")])
        service = _service(FakeUsers(), notifier=notifier, reminders=reminders)

        assert service.count_due(now=NOW) == 1
        assert not notifier.verifications


class TestRequestChange:
    def test_new_address_goes_pending_with_both_mails(self):
        users = FakeUsers(users=[_user(email="old@example.com", email_verified=True)])
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        outcome = service.request_change(
            user_slug="auth0user", new_address="new@example.com"
        )

        assert outcome == ChangeRequestOutcome.REQUESTED
        assert ("auth0user", {"pending_email": "new@example.com"}) in users.updated
        assert notifier.verifications[0].recipient_email == "new@example.com"
        assert notifier.change_requests[0].recipient_email == "old@example.com"
        assert notifier.change_requests[0].new_address == "new@example.com"

    def test_cancel_token_binds_the_pending_address(self):
        users = FakeUsers(users=[_user(email="old@example.com", email_verified=True)])
        codec = FakeCodec()
        service = _service(users, codec=codec)

        service.request_change(user_slug="auth0user", new_address="new@example.com")

        cancel = [
            payload
            for payload in codec.minted
            if payload.act is EmailVerificationAction.CANCEL
        ]
        assert len(cancel) == 1
        assert cancel[0].addr == "new@example.com"

    def test_first_address_sends_no_cancel_notice(self):
        users = FakeUsers(users=[_user(email="")])
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        outcome = service.request_change(
            user_slug="auth0user", new_address="new@example.com"
        )

        assert outcome == ChangeRequestOutcome.REQUESTED
        assert not notifier.change_requests

    def test_unproven_old_address_gets_no_cancel_notice(self):
        users = FakeUsers(users=[_user(email="old@example.com", email_verified=False)])
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        outcome = service.request_change(
            user_slug="auth0user", new_address="new@example.com"
        )

        assert outcome == ChangeRequestOutcome.REQUESTED
        assert not notifier.change_requests

    def test_current_address_is_unchanged(self):
        users = FakeUsers(users=[_user(email="mine@example.com")])
        service = _service(users)

        outcome = service.request_change(
            user_slug="auth0user", new_address="mine@example.com"
        )

        assert outcome == ChangeRequestOutcome.UNCHANGED
        assert not users.updated

    def test_pending_address_is_unchanged(self):
        users = FakeUsers(
            users=[_user(email="old@example.com", pending_email="new@example.com")]
        )
        service = _service(users)

        outcome = service.request_change(
            user_slug="auth0user", new_address="new@example.com"
        )

        assert outcome == ChangeRequestOutcome.UNCHANGED

    def test_blank_clears_everything(self):
        users = FakeUsers(users=[_user(email="mine@example.com", email_verified=True)])
        service = _service(users)

        outcome = service.request_change(user_slug="auth0user", new_address="")

        assert outcome == ChangeRequestOutcome.CLEARED
        assert users.updated == [
            (
                "auth0user",
                {
                    "email": "",
                    "email_verified": False,
                    "pending_email": "",
                    "email_verification_sent_at": None,
                },
            )
        ]

    def test_blank_on_empty_account_is_unchanged(self):
        users = FakeUsers(users=[_user(email="")])
        service = _service(users)

        outcome = service.request_change(user_slug="auth0user", new_address="")

        assert outcome == ChangeRequestOutcome.UNCHANGED
        assert not users.updated

    def test_taken_address_is_rejected_without_writes(self):
        users = FakeUsers(
            users=[_user(email="old@example.com")],
            existing_emails={"taken@example.com"},
        )
        service = _service(users)

        outcome = service.request_change(
            user_slug="auth0user", new_address="taken@example.com"
        )

        assert outcome == ChangeRequestOutcome.TAKEN
        assert not users.updated


class TestDescribe:
    def test_valid_confirm_link(self):
        users = FakeUsers(users=[_user(email="mine@example.com")])
        service = _service(users)

        link = service.describe(
            _token(EmailVerificationAction.CONFIRM, "mine@example.com")
        )

        assert link is not None
        assert link.action is EmailVerificationAction.CONFIRM
        assert link.address == "mine@example.com"

    def test_expired_or_garbled_token(self):
        users = FakeUsers(users=[_user(email="mine@example.com")])
        service = _service(users)

        assert service.describe("garbage") is None

    def test_spent_link(self):
        users = FakeUsers(users=[_user(email="mine@example.com", email_verified=True)])
        service = _service(users)

        assert (
            service.describe(
                _token(EmailVerificationAction.CONFIRM, "mine@example.com")
            )
            is None
        )

    def test_cancel_link_for_pending_change(self):
        users = FakeUsers(
            users=[_user(email="old@example.com", pending_email="new@example.com")]
        )
        service = _service(users)

        link = service.describe(
            _token(EmailVerificationAction.CANCEL, "new@example.com")
        )

        assert link is not None
        assert link.action is EmailVerificationAction.CANCEL


class TestRedeem:
    def test_confirm_own_address(self):
        users = FakeUsers(users=[_user(email="mine@example.com")])
        service = _service(users)

        result = service.redeem(
            _token(EmailVerificationAction.CONFIRM, "mine@example.com")
        )

        assert result.outcome == RedeemOutcome.VERIFIED
        assert users.updated == [("auth0user", {"email_verified": True})]

    def test_confirm_promotes_pending_change(self):
        users = FakeUsers(
            users=[
                _user(
                    email="old@example.com",
                    email_verified=True,
                    pending_email="new@example.com",
                )
            ]
        )
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        result = service.redeem(
            _token(EmailVerificationAction.CONFIRM, "new@example.com")
        )

        assert result.outcome == RedeemOutcome.CHANGE_APPLIED
        assert users.updated == [
            (
                "auth0user",
                {
                    "email": "new@example.com",
                    "email_verified": True,
                    "pending_email": "",
                },
            )
        ]
        assert notifier.change_completions[0].recipient_email == "old@example.com"
        assert notifier.change_completions[0].new_address == "new@example.com"

    def test_confirm_of_unproven_old_address_sends_no_completion_notice(self):
        users = FakeUsers(
            users=[
                _user(
                    email="old@example.com",
                    email_verified=False,
                    pending_email="new@example.com",
                )
            ]
        )
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        result = service.redeem(
            _token(EmailVerificationAction.CONFIRM, "new@example.com")
        )

        assert result.outcome == RedeemOutcome.CHANGE_APPLIED
        assert not notifier.change_completions

    def test_confirm_first_address_reports_verified(self):
        users = FakeUsers(users=[_user(email="", pending_email="new@example.com")])
        notifier = FakeNotifier()
        service = _service(users, notifier=notifier)

        result = service.redeem(
            _token(EmailVerificationAction.CONFIRM, "new@example.com")
        )

        assert result.outcome == RedeemOutcome.VERIFIED
        assert not notifier.change_completions

    def test_cancel_drops_pending_change(self):
        users = FakeUsers(
            users=[_user(email="old@example.com", pending_email="new@example.com")]
        )
        service = _service(users)

        result = service.redeem(
            _token(EmailVerificationAction.CANCEL, "new@example.com")
        )

        assert result.outcome == RedeemOutcome.CANCELLED
        assert users.updated == [("auth0user", {"pending_email": ""})]

    def test_expired_token(self):
        service = _service(FakeUsers(users=[_user()]))

        assert service.redeem("garbage").outcome == RedeemOutcome.EXPIRED

    def test_unknown_user(self):
        service = _service(FakeUsers())

        result = service.redeem(
            _token(EmailVerificationAction.CONFIRM, "mine@example.com")
        )

        assert result.outcome == RedeemOutcome.EXPIRED

    def test_replayed_link_is_spent(self):
        users = FakeUsers(users=[_user(email="mine@example.com", email_verified=True)])
        service = _service(users)

        result = service.redeem(
            _token(EmailVerificationAction.CONFIRM, "mine@example.com")
        )

        assert result.outcome == RedeemOutcome.ALREADY_USED

    def test_cancel_after_cancel_is_spent(self):
        users = FakeUsers(users=[_user(email="old@example.com", pending_email="")])
        service = _service(users)

        result = service.redeem(
            _token(EmailVerificationAction.CANCEL, "new@example.com")
        )

        assert result.outcome == RedeemOutcome.ALREADY_USED

    def test_lost_promote_race_reports_taken_and_drops_pending(self):
        users = FakeUsers(
            users=[_user(email="old@example.com", pending_email="new@example.com")],
            constraint_on_email="new@example.com",
        )
        service = _service(users)

        result = service.redeem(
            _token(EmailVerificationAction.CONFIRM, "new@example.com")
        )

        assert result.outcome == RedeemOutcome.ADDRESS_TAKEN
        assert users.updated == [("auth0user", {"pending_email": ""})]
