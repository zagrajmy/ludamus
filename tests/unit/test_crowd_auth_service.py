import math
from contextlib import contextmanager

import pytest

from ludamus.mills.crowd import CrowdAuthService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import ClaimOutcome, ClaimResultDTO, UserDTO
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import user_dto


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0
        self.savepoints = 0

    def atomic(self):
        self.entered += 1
        return _atomic()

    def savepoint(self):
        self.savepoints += 1
        return _atomic()


def _user_dto(**overrides) -> UserDTO:
    return user_dto(**{"slug": "auth0user", **overrides})


class FakeUsers:
    def __init__(self, *, users=(), existing_emails=()):
        self._users = list(users)
        self._existing_emails = set(existing_emails)
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
        return (
            any(
                user.email == email and user.slug != exclude_slug
                for user in self._users
            )
            or email in self._existing_emails
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
    def __init__(self, result=None):
        self._result = result or ClaimResultDTO(outcome=ClaimOutcome.INVALID)
        self.redeemed = []

    def issue(self, *, manager_slug, user_slug):
        raise NotImplementedError

    def read_claimable(self, token):
        raise NotImplementedError

    def redeem(self, *, token, username):
        self.redeemed.append((token, username))
        return self._result


class FakeSpheres:
    def __init__(self, domains=()):
        self._domains = set(domains)

    def domain_exists(self, domain):
        return domain in self._domains


def _service(*, users, claims=None, spheres=None, transaction=None):
    return CrowdAuthService(
        transaction=transaction or FakeTransaction(),
        users=users,
        spheres=spheres or FakeSpheres(),
        claims=claims or FakeClaims(),
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
