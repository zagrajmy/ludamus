import math
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from ludamus.mills.crowd import CrowdAuthService
from ludamus.pacts import NotFoundError
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import user_dto

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()

    @staticmethod
    def savepoint():
        return _atomic()


def _user_dto(**overrides) -> UserDTO:
    return user_dto(**{"slug": "auth0user", **overrides})


class FakeUsers:
    def __init__(self, *, users=()):
        self._users = list(users)
        self.updated = []

    def read(self, slug):
        for user in self._users:
            if user.slug == slug:
                return user
        raise NotFoundError

    def update(self, user_slug, user_data):
        self.updated.append((user_slug, user_data))
        for index, user in enumerate(self._users):
            if user.slug == user_slug:
                self._users[index] = user.model_copy(update=dict(user_data))

    def email_exists(self, email, exclude_slug=None):
        if not email:
            return False
        return any(
            user.email == email and user.slug != exclude_slug for user in self._users
        )


class _RacingUsers:
    # create raises the constraint error a concurrent inserter would trigger,
    # and read_by_username misses for the first `misses` calls. misses=1 is the
    # race: the concurrent row becomes visible on the retry. misses=inf is the
    # unadoptable insert: there is no row, so the error was not a race.
    def __init__(self, misses=1):
        self.create_attempts = 0
        self._misses = misses
        self._reads = 0

    def read_by_username(self, username):
        self._reads += 1
        if self._reads <= self._misses:
            raise NotFoundError
        return _user_dto(username=username)

    @staticmethod
    def email_exists(email, exclude_slug=None):
        _ = (email, exclude_slug)
        return False

    @staticmethod
    def slug_exists(slug):
        _ = slug
        return False

    def create(self, user_data):
        _ = user_data
        self.create_attempts += 1
        raise DatabaseConstraintError("duplicate key")


class FakeClaims:
    pass


class FakeSpheres:
    @staticmethod
    def domain_exists(domain):
        _ = domain
        return False


def _service(*, users):
    return CrowdAuthService(
        transaction=FakeTransaction(),
        users=users,
        spheres=FakeSpheres(),
        claims=FakeClaims(),
    )


class TestProvisionUser:
    def test_concurrent_insert_is_adopted(self):
        # read_by_username misses, then create raises the unique-constraint
        # error because a concurrent callback already inserted the row; the
        # service swallows it and re-reads the now-present user.
        users = _RacingUsers()
        service = _service(users=users)

        result = service.provision_user(
            username="auth0|sub",
            create_data={"slug": "auth0user", "username": "auth0|sub"},
        )

        assert result.user.username == "auth0|sub"
        assert users.create_attempts == 1

    def test_unadoptable_constraint_error_surfaces(self):
        # The insert fails and no row can be read back, so the real database
        # error must propagate instead of a bare NotFoundError.
        service = _service(users=_RacingUsers(misses=math.inf))

        with pytest.raises(DatabaseConstraintError):
            service.provision_user(
                username="auth0|sub",
                create_data={"slug": "auth0user", "username": "auth0|sub"},
            )


class TestSyncIdentity:
    def test_own_email_is_not_a_collision(self):
        users = FakeUsers(users=[_user_dto(email="mine@example.com")])
        service = _service(users=users)

        service.sync_identity(user_slug="auth0user", data={"email": "mine@example.com"})

        assert users.updated == [("auth0user", {"email": "mine@example.com"})]
