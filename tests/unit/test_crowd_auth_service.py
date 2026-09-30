import math
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from ludamus.mills.crowd import ClaimService, CrowdAuthService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import ClaimableProfileDTO, ClaimOutcome, ClaimResultDTO
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import user_dto

_TOKEN_MIN_LENGTH = 48

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
        self.created = []

    def read(self, slug):
        return next(user for user in self._users if user.slug == slug)

    def read_by_username(self, username):
        for user in self._users:
            if user.username == username:
                return user
        raise NotFoundError

    def create(self, user_data):
        self.created.append(dict(user_data))
        self._users.append(
            _user_dto(
                pk=len(self._users) + 1,
                slug=user_data["slug"],
                username=user_data.get("username", ""),
                email=user_data.get("email", ""),
            )
        )

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


class FakeClaimRepo:
    def __init__(self, *, claimable=None, usernames=(), accept=True):
        self._claimable = claimable
        self._usernames = set(usernames)
        self._accept = accept
        self.issued = []
        self.converted = []

    def issue_token(self, *, manager_slug, user_slug, token):
        self.issued.append((manager_slug, user_slug, token))
        return self._accept

    def read_claimable(self, token):
        return self._claimable if token == "valid" else None

    def username_exists(self, username):
        return username in self._usernames

    def convert(self, *, token, username):
        if token != "valid":
            return None
        self.converted.append((token, username))
        return self._claimable.slug


class FakeClaims:
    def __init__(self, result=None):
        self._result = result

    def redeem(self, *, token, username):
        _ = (token, username)
        return self._result


class FakeSpheres:
    def __init__(self, domains=()):
        self._domains = set(domains)

    def domain_exists(self, domain):
        return domain in self._domains


def _service(*, users, claims=None, spheres=None):
    return CrowdAuthService(
        transaction=FakeTransaction(),
        users=users,
        spheres=spheres or FakeSpheres(),
        claims=claims or FakeClaims(),
    )


def _claim_service(repo):
    return ClaimService(FakeTransaction(), repo)


def _claimable():
    return ClaimableProfileDTO(name="Kid", slug="kid", manager_name="Parent")


class TestClaimServiceIssue:
    def test_returns_a_fresh_token_the_repo_recorded(self):
        repo = FakeClaimRepo()

        token = _claim_service(repo).issue(manager_slug="parent", user_slug="kid")

        assert token is not None
        assert len(token) >= _TOKEN_MIN_LENGTH
        assert repo.issued == [("parent", "kid", token)]

    def test_refused_by_repo_yields_none(self):
        repo = FakeClaimRepo(accept=False)

        assert _claim_service(repo).issue(manager_slug="parent", user_slug="x") is None

    def test_read_claimable_passes_through(self):
        service = _claim_service(FakeClaimRepo(claimable=_claimable()))

        assert service.read_claimable("valid") == _claimable()
        assert service.read_claimable("spent") is None


class TestClaimServiceRedeem:
    def test_recipient_already_has_an_account(self):
        repo = FakeClaimRepo(claimable=_claimable(), usernames=["auth0|sub"])

        result = _claim_service(repo).redeem(token="valid", username="auth0|sub")

        assert result == ClaimResultDTO(outcome=ClaimOutcome.ALREADY_AUTHENTICATED)
        assert not repo.converted

    def test_unknown_or_spent_token_is_invalid(self):
        repo = FakeClaimRepo(claimable=_claimable())

        result = _claim_service(repo).redeem(token="spent", username="auth0|sub")

        assert result == ClaimResultDTO(outcome=ClaimOutcome.INVALID)

    def test_converts_the_profile_row(self):
        repo = FakeClaimRepo(claimable=_claimable())

        result = _claim_service(repo).redeem(token="valid", username="auth0|sub")

        assert result == ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug="kid")
        assert repo.converted == [("valid", "auth0|sub")]


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

    def test_existing_user_is_returned_without_a_claim(self):
        users = FakeUsers(users=[_user_dto(username="auth0|sub")])

        result = _service(users=users).provision_user(
            username="auth0|sub", create_data={"slug": "auth0user"}
        )

        assert result.user.slug == "auth0user"
        assert result.claim_outcome is None
        assert not users.created

    def test_converted_claim_returns_the_claimed_profile(self):
        users = FakeUsers(users=[_user_dto(slug="kid", username="auth0|sub")])
        claims = FakeClaims(
            ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug="kid")
        )

        result = _service(users=users, claims=claims).provision_user(
            username="auth0|sub", create_data={"slug": "other"}, claim_token="valid"
        )

        assert result.user.slug == "kid"
        assert result.claim_outcome == ClaimOutcome.CONVERTED
        assert not users.created

    def test_invalid_claim_still_provisions_and_reports_it(self):
        users = FakeUsers()
        claims = FakeClaims(ClaimResultDTO(outcome=ClaimOutcome.INVALID))

        result = _service(users=users, claims=claims).provision_user(
            username="auth0|sub",
            create_data={"slug": "auth0user", "username": "auth0|sub"},
            claim_token="spent",
        )

        assert result.claim_outcome == ClaimOutcome.INVALID
        assert result.user.username == "auth0|sub"

    def test_taken_email_is_dropped_on_create(self):
        users = FakeUsers(
            users=[_user_dto(slug="other", username="x", email="dup@example.com")]
        )

        result = _service(users=users).provision_user(
            username="auth0|sub",
            create_data={
                "slug": "auth0user",
                "username": "auth0|sub",
                "email": "dup@example.com",
            },
        )

        assert not result.user.email
        assert not users.created[0]["email"]

    def test_taken_slug_is_uniquified(self):
        users = FakeUsers(users=[_user_dto(slug="auth0user", username="someone")])

        result = _service(users=users).provision_user(
            username="auth0|sub",
            create_data={"slug": "auth0user", "username": "auth0|sub"},
        )

        assert result.user.slug != "auth0user"
        assert result.user.slug.startswith("auth0user-")


class TestSyncIdentity:
    def test_own_email_is_not_a_collision(self):
        users = FakeUsers(users=[_user_dto(email="mine@example.com")])
        service = _service(users=users)

        service.sync_identity(user_slug="auth0user", data={"email": "mine@example.com"})

        assert users.updated == [("auth0user", {"email": "mine@example.com"})]

    def test_someone_elses_email_is_not_synced(self):
        users = FakeUsers(
            users=[_user_dto(), _user_dto(slug="other", email="theirs@example.com")]
        )

        result = _service(users=users).sync_identity(
            user_slug="auth0user", data={"email": "theirs@example.com", "name": "New"}
        )

        assert users.updated == [("auth0user", {"name": "New"})]
        assert result.name == "New"
        assert not result.email

    def test_nothing_left_to_sync_skips_the_write(self):
        users = FakeUsers(
            users=[_user_dto(), _user_dto(slug="other", email="theirs@example.com")]
        )

        result = _service(users=users).sync_identity(
            user_slug="auth0user", data={"email": "theirs@example.com"}
        )

        assert not users.updated
        assert result.slug == "auth0user"


class TestIsKnownSphereDomain:
    def test_answers_from_the_sphere_repo(self):
        service = _service(users=FakeUsers(), spheres=FakeSpheres(["a.example.com"]))

        assert service.is_known_sphere_domain("a.example.com") is True
        assert service.is_known_sphere_domain("b.example.com") is False
