from datetime import timedelta

import pytest
from django.utils import timezone

from ludamus.links.db.django.crowd import UserRepository
from ludamus.pacts.crowd import UserType
from ludamus.specs.crowd import EMAIL_VERIFICATION_RESEND_THROTTLE
from tests.integration.conftest import UserFactory

pytestmark = pytest.mark.django_db

_repo = UserRepository(UserType.ACTIVE)


class TestClaimVerificationSend:
    def test_never_sent_row_wins_the_slot(self):
        now = timezone.now()
        user = UserFactory(email="mine@example.com", email_verification_sent_at=None)

        claimed = _repo.claim_verification_send(
            user_slug=user.slug, now=now, throttle=EMAIL_VERIFICATION_RESEND_THROTTLE
        )

        user.refresh_from_db()
        assert claimed is True
        assert user.email_verification_sent_at == now

    def test_stale_row_wins_the_slot(self):
        now = timezone.now()
        user = UserFactory(
            email="mine@example.com",
            email_verification_sent_at=now - EMAIL_VERIFICATION_RESEND_THROTTLE,
        )

        claimed = _repo.claim_verification_send(
            user_slug=user.slug, now=now, throttle=EMAIL_VERIFICATION_RESEND_THROTTLE
        )

        user.refresh_from_db()
        assert claimed is True
        assert user.email_verification_sent_at == now

    def test_recently_stamped_row_loses_the_slot(self):
        now = timezone.now()
        sent_at = now - timedelta(minutes=1)
        user = UserFactory(email="mine@example.com", email_verification_sent_at=sent_at)

        claimed = _repo.claim_verification_send(
            user_slug=user.slug, now=now, throttle=EMAIL_VERIFICATION_RESEND_THROTTLE
        )

        user.refresh_from_db()
        assert claimed is False
        assert user.email_verification_sent_at == sent_at

    def test_second_caller_loses_the_slot_the_first_took(self):
        now = timezone.now()
        user = UserFactory(email="mine@example.com", email_verification_sent_at=None)

        first = _repo.claim_verification_send(
            user_slug=user.slug, now=now, throttle=EMAIL_VERIFICATION_RESEND_THROTTLE
        )
        second = _repo.claim_verification_send(
            user_slug=user.slug, now=now, throttle=EMAIL_VERIFICATION_RESEND_THROTTLE
        )

        assert first is True
        assert second is False

    def test_unknown_slug_claims_nothing(self):
        assert (
            _repo.claim_verification_send(
                user_slug="ghost",
                now=timezone.now(),
                throttle=EMAIL_VERIFICATION_RESEND_THROTTLE,
            )
            is False
        )
