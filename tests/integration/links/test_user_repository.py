import pytest
from django.contrib.auth.hashers import make_password

from ludamus.links.db.django.crowd import UserRepository
from ludamus.links.db.django.models import User
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import UserType
from tests.integration.conftest import UserFactory

REPO = UserRepository(UserType.ACTIVE)


class TestReadByEmail:
    def test_matches_case_insensitively(self):
        user = UserFactory(username="workos|a", email="Me@Example.com")

        assert REPO.read_by_email("me@example.com").slug == user.slug

    @pytest.mark.parametrize("email", ("", "nobody@example.com"))
    def test_blank_or_unknown_is_not_found(self, email):
        UserFactory(username="workos|blank", email="")

        with pytest.raises(NotFoundError):
            REPO.read_by_email(email)


class TestCreate:
    def test_without_password_the_account_cannot_log_in_by_password(self):
        REPO.create({"username": "workos|new", "slug": "new"})

        assert not User.objects.get(slug="new").has_usable_password()

    def test_given_password_is_kept(self):
        REPO.create(
            {"username": "local", "slug": "local", "password": make_password("pw")}
        )

        assert User.objects.get(slug="local").check_password("pw")
