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
    def __init__(self, *, users=(), existing_emails=()):
        self._users = list(users)
        self._existing_emails = set(existing_emails)
        self.created = []
        self.updated = []

    def create(self, user_data):
        self.created.append(user_data)
        self._users.append(
            _user_dto(
                slug=user_data.get("slug", ""),
                username=user_data.get("username", ""),
                email=user_data.get("email", ""),
                email_verified=user_data.get("email_verified", False),
                name=user_data.get("name", ""),
            )
        )

    def read(self, slug):
        for user in self._users:
            if user.slug == slug:
                return user
        raise NotFoundError

    def read_by_username(self, username):
        for user in self._users:
            if user.username == username:
                return user
        raise NotFoundError

    def update(self, user_slug, user_data):
        self.updated.append((user_slug, user_data))
        for index, user in enumerate(self._users):
            if user.slug == user_slug:
                self._users[index] = user.model_copy(update=dict(user_data))

    def email_unavailable(self, *, email, now, exclude_slug=None):
        _ = now
        if not email:
            return False
        return (
            any(
                user.email == email and user.slug != exclude_slug
                for user in self._users
            )
            or email in self._existing_emails
        )

    def slug_exists(self, slug):
        return any(user.slug == slug for user in self._users)


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
    def email_unavailable(*, email, now, exclude_slug=None):
        _ = (email, now, exclude_slug)
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
    def test_create_strips_duplicate_email_and_reports_conflict(self):
        users = FakeUsers(existing_emails={"taken@example.com"})
        service = _service(users=users)

        result = service.provision_user(
            username="auth0|sub",
            create_data={
                "slug": "auth0user",
                "username": "auth0|sub",
                "email": "taken@example.com",
            },
        )

        assert users.created == [
            {
                "slug": "auth0user",
                "username": "auth0|sub",
                "email": "",
                "email_verified": False,
            }
        ]
        assert result.email_conflict is True

    def test_create_without_conflict_reports_none(self):
        users = FakeUsers()
        service = _service(users=users)

        result = service.provision_user(
            username="auth0|sub",
            create_data={
                "slug": "auth0user",
                "username": "auth0|sub",
                "email": "new@example.com",
            },
        )

        assert result.email_conflict is False

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
    def test_same_address_unverified_claim_is_a_noop(self):
        users = FakeUsers(users=[_user_dto(email="mine@example.com")])
        service = _service(users=users)

        service.sync_identity(user_slug="auth0user", data={"email": "mine@example.com"})

        assert not users.updated

    def test_verified_claim_on_same_address_sets_flag(self):
        users = FakeUsers(users=[_user_dto(email="mine@example.com")])
        service = _service(users=users)

        user = service.sync_identity(
            user_slug="auth0user",
            data={"email": "mine@example.com", "email_verified": True},
        )

        assert users.updated == [("auth0user", {"email_verified": True})]
        assert user.email_verified is True

    def test_verified_stored_address_is_not_reverted(self):
        users = FakeUsers(
            users=[_user_dto(email="chosen@example.com", email_verified=True)]
        )
        service = _service(users=users)

        user = service.sync_identity(
            user_slug="auth0user",
            data={"email": "idp@example.com", "email_verified": True},
        )

        assert not users.updated
        assert user.email == "chosen@example.com"

    def test_new_address_carries_claim_verified_flag(self):
        users = FakeUsers(users=[_user_dto(email="")])
        service = _service(users=users)

        service.sync_identity(
            user_slug="auth0user",
            data={"email": "new@example.com", "email_verified": True},
        )

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

    def test_unverified_stored_address_is_replaced(self):
        users = FakeUsers(
            users=[_user_dto(email="typo@example.com", email_verified=False)]
        )
        service = _service(users=users)

        service.sync_identity(
            user_slug="auth0user",
            data={"email": "idp@example.com", "email_verified": False},
        )

        assert users.updated == [
            (
                "auth0user",
                {
                    "email": "idp@example.com",
                    "email_verified": False,
                    "pending_email": "",
                },
            )
        ]

    def test_existing_name_is_not_overwritten(self):
        users = FakeUsers(users=[_user_dto(name="Have Name")])
        service = _service(users=users)

        service.sync_identity(user_slug="auth0user", data={"name": "Claim Name"})

        assert not users.updated

    def test_unchanged_avatar_is_skipped(self):
        users = FakeUsers(users=[_user_dto(avatar_url="https://a/x.png")])
        service = _service(users=users)

        service.sync_identity(
            user_slug="auth0user", data={"avatar_url": "https://a/x.png"}
        )

        assert not users.updated
