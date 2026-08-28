from datetime import timedelta

import pytest
from django.utils import timezone

from ludamus.links.db.django.crowd import UserRepository
from ludamus.pacts.crowd import EMAIL_LINK_MAX_AGE, UserType
from tests.integration.conftest import UserFactory

pytestmark = pytest.mark.django_db

_repo = UserRepository(UserType.ACTIVE)


class TestEmailExists:
    def test_matches_live_address_case_insensitively(self):
        UserFactory(email="taken@example.com")

        assert _repo.email_exists("Taken@Example.com") is True

    def test_blank_never_exists(self):
        UserFactory(email="")

        assert _repo.email_exists("") is False

    def test_excludes_own_slug(self):
        user = UserFactory(email="mine@example.com")

        assert _repo.email_exists("mine@example.com", exclude_slug=user.slug) is False

    def test_live_pending_address_is_reserved(self):
        UserFactory(
            email="old@example.com",
            pending_email="new@example.com",
            email_verification_sent_at=timezone.now(),
        )

        assert _repo.email_exists("new@example.com") is True

    def test_expired_pending_reservation_is_released(self):
        UserFactory(
            email="old@example.com",
            pending_email="new@example.com",
            email_verification_sent_at=timezone.now()
            - EMAIL_LINK_MAX_AGE
            - timedelta(minutes=1),
        )

        assert _repo.email_exists("new@example.com") is False
