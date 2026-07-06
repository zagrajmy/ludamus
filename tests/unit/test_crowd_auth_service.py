from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.crowd import CrowdAuthService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import ClaimOutcome, ClaimResultDTO, UserDTO, UserType
from ludamus.pacts.services import DatabaseConstraintError


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
    defaults = {
        "avatar_url": "",
        "date_joined": datetime(2024, 1, 1, tzinfo=UTC),
        "discord_username": "",
        "email": "",
        "full_name": "",
        "is_active": True,
        "is_authenticated": True,
        "is_staff": False,
        "is_superuser": False,
        "name": "",
        "pk": 1,
        "slug": "auth0user",
        "use_gravatar": False,
        "user_type": UserType.ACTIVE,
        "username": "auth0|sub",
    }
    return UserDTO(**(defaults | overrides))


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
    # read_by_username misses on the first call (before the concurrent insert
    # is visible) and hits on the second; create raises the constraint error a
    # concurrent inserter would trigger.
    def __init__(self):
        self.create_attempts = 0
        self._reads = 0

    def read_by_username(self, username):
        self._reads += 1
        if self._reads == 1:
            raise NotFoundError
        return _user_dto(username=username)

    @staticmethod
    def email_exists(email, exclude_slug=None):
        _ = (email, exclude_slug)
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
    def test_returns_existing_user_without_create(self):
        users = FakeUsers(users=[_user_dto()])
        service = _service(users=users)

        result = service.provision_user(
            username="auth0|sub", create_data={"username": "auth0|sub"}
        )

        assert result.user.username == "auth0|sub"
        assert result.claim_outcome is None
        assert not users.created

    def test_creates_missing_user_in_transaction(self):
        users = FakeUsers()
        transaction = FakeTransaction()
        service = _service(users=users, transaction=transaction)

        result = service.provision_user(
            username="auth0|sub",
            create_data={
                "slug": "auth0user",
                "username": "auth0|sub",
                "email": "new@example.com",
            },
        )

        assert transaction.savepoints == 1
        assert users.created == [
            {"slug": "auth0user", "username": "auth0|sub", "email": "new@example.com"}
        ]
        assert result.user.username == "auth0|sub"

    def test_create_strips_duplicate_email(self):
        users = FakeUsers(existing_emails={"taken@example.com"})
        service = _service(users=users)

        service.provision_user(
            username="auth0|sub",
            create_data={
                "slug": "auth0user",
                "username": "auth0|sub",
                "email": "taken@example.com",
            },
        )

        assert users.created == [
            {"slug": "auth0user", "username": "auth0|sub", "email": ""}
        ]

    def test_converted_claim_returns_claimed_user(self):
        claimed = _user_dto(slug="kid", username="auth0|sub")
        users = FakeUsers(users=[claimed])
        claims = FakeClaims(
            ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug="kid")
        )
        service = _service(users=users, claims=claims)

        result = service.provision_user(
            username="auth0|sub",
            create_data={"username": "auth0|sub"},
            claim_token="token",
        )

        assert claims.redeemed == [("token", "auth0|sub")]
        assert result.claim_outcome == ClaimOutcome.CONVERTED
        assert result.user.slug == "kid"
        assert not users.created

    def test_failed_claim_falls_through_to_get_or_create(self):
        users = FakeUsers(users=[_user_dto()])
        claims = FakeClaims(ClaimResultDTO(outcome=ClaimOutcome.ALREADY_AUTHENTICATED))
        service = _service(users=users, claims=claims)

        result = service.provision_user(
            username="auth0|sub",
            create_data={"username": "auth0|sub"},
            claim_token="token",
        )

        assert result.claim_outcome == ClaimOutcome.ALREADY_AUTHENTICATED
        assert result.user.username == "auth0|sub"

    def test_no_claim_token_skips_redemption(self):
        claims = FakeClaims()
        service = _service(users=FakeUsers(users=[_user_dto()]), claims=claims)

        service.provision_user(
            username="auth0|sub", create_data={"username": "auth0|sub"}
        )

        assert not claims.redeemed

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


class TestSyncIdentity:
    def test_updates_in_transaction_and_returns_fresh_user(self):
        users = FakeUsers(users=[_user_dto()])
        transaction = FakeTransaction()
        service = _service(users=users, transaction=transaction)

        user = service.sync_identity(user_slug="auth0user", data={"name": "New Name"})

        assert transaction.entered == 1
        assert users.updated == [("auth0user", {"name": "New Name"})]
        assert user.name == "New Name"

    def test_drops_colliding_email_but_applies_rest(self):
        users = FakeUsers(users=[_user_dto()], existing_emails={"taken@example.com"})
        service = _service(users=users)

        service.sync_identity(
            user_slug="auth0user",
            data={"email": "taken@example.com", "name": "New Name"},
        )

        assert users.updated == [("auth0user", {"name": "New Name"})]

    def test_only_colliding_email_skips_update(self):
        users = FakeUsers(users=[_user_dto()], existing_emails={"taken@example.com"})
        transaction = FakeTransaction()
        service = _service(users=users, transaction=transaction)

        user = service.sync_identity(
            user_slug="auth0user", data={"email": "taken@example.com"}
        )

        assert transaction.entered == 0
        assert not users.updated
        assert user.slug == "auth0user"

    def test_own_email_is_not_a_collision(self):
        users = FakeUsers(users=[_user_dto(email="mine@example.com")])
        service = _service(users=users)

        service.sync_identity(user_slug="auth0user", data={"email": "mine@example.com"})

        assert users.updated == [("auth0user", {"email": "mine@example.com"})]


class TestIsKnownSphereDomain:
    def test_known_domain(self):
        service = _service(users=FakeUsers(), spheres=FakeSpheres({"example.com"}))

        assert service.is_known_sphere_domain("example.com") is True

    def test_unknown_domain(self):
        service = _service(users=FakeUsers(), spheres=FakeSpheres())

        assert service.is_known_sphere_domain("malicious.com") is False
