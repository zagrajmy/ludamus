from datetime import timedelta

import pytest
from django.utils import timezone

from ludamus.links.db.django.crowd import UserRepository
from ludamus.pacts.crowd import EMAIL_LINK_MAX_AGE, UserType
from tests.integration.conftest import UserFactory

pytestmark = pytest.mark.django_db

_repo = UserRepository(UserType.ACTIVE)


class TestEmailUnavailable:
    def test_matches_live_address_case_insensitively(self):
        UserFactory(email="taken@example.com")

        assert (
            _repo.email_unavailable(email="Taken@Example.com", now=timezone.now())
            is True
        )

    def test_blank_is_always_available(self):
        UserFactory(email="")

        assert _repo.email_unavailable(email="", now=timezone.now()) is False

    def test_excludes_own_slug(self):
        user = UserFactory(email="mine@example.com")

        assert (
            _repo.email_unavailable(
                email="mine@example.com", now=timezone.now(), exclude_slug=user.slug
            )
            is False
        )

    def test_live_pending_address_is_reserved(self):
        UserFactory(
            email="old@example.com",
            pending_email="new@example.com",
            email_verification_sent_at=timezone.now(),
        )

        assert (
            _repo.email_unavailable(email="new@example.com", now=timezone.now()) is True
        )

    def test_expired_pending_reservation_is_released(self):
        sent_at = timezone.now()
        UserFactory(
            email="old@example.com",
            pending_email="new@example.com",
            email_verification_sent_at=sent_at,
        )

        assert (
            _repo.email_unavailable(
                email="new@example.com",
                now=sent_at + EMAIL_LINK_MAX_AGE + timedelta(minutes=1),
            )
            is False
        )
