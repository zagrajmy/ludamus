import math
from contextlib import contextmanager

import pytest

from ludamus.mills.crowd import CrowdAuthService, LegacyAccountLinker
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    MAX_AVATAR_URL_LENGTH,
    AuthenticationDTO,
    ClaimOutcome,
    ClaimResultDTO,
    IdentityDTO,
    UserDTO,
)
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import user_dto

SLUG_MAX_LENGTH = 50
USERNAME = "workos|user_01ME"


def _identity(**overrides) -> IdentityDTO:
    return IdentityDTO(
        **{
            "provider_user_id": "user_01ME",
            "email": "",
            "email_verified": True,
            "name": "",
            "avatar_url": "",
            "legacy_id": "",
        }
        | overrides
    )


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
    return user_dto(**{"slug": "me", "username": USERNAME, **overrides})


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

    def read_by_email(self, email):
        for user in self._users:
            if email and user.email.lower() == email.lower():
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
    def read_by_email(email):
        raise NotFoundError(email)

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


class FakeIdentity:
    def __init__(self, identity=None):
        self.identity = identity or _identity()
        self.codes = []

    def authorization_url(self, *, redirect_uri, state, sign_up):
        return f"https://idp.example/authorize?{redirect_uri}&{state}&{sign_up}"

    def authenticate(self, code):
        self.codes.append(code)
        return AuthenticationDTO(identity=self.identity, session_id="session_01")

    @staticmethod
    def logout_url(*, session_id, return_to):
        return f"https://idp.example/logout?{session_id}&{return_to}"


def _service(*, users, claims=None, spheres=None, transaction=None, identity=None):
    return CrowdAuthService(
        transaction=transaction or FakeTransaction(),
        users=users,
        spheres=spheres or FakeSpheres(),
        claims=claims or FakeClaims(),
        identity=identity or FakeIdentity(),
        legacy_accounts=LegacyAccountLinker(users=users),
    )


def _login(service, **kwargs):
    return service.complete_login(code="code", **kwargs)


class TestProviderUrls:
    def test_login_url_delegates(self):
        service = _service(users=FakeUsers())

        url = service.login_url(redirect_uri="cb", state="st", sign_up=True)

        assert url == "https://idp.example/authorize?cb&st&True"

    def test_logout_url_delegates(self):
        service = _service(users=FakeUsers())

        url = service.logout_url(session_id="session_01", return_to="back")

        assert url == "https://idp.example/logout?session_01&back"


class TestCompleteLogin:
    def test_returns_existing_user_without_create(self):
        users = FakeUsers(users=[_user_dto()])
        identity = FakeIdentity()
        service = _service(users=users, identity=identity)

        result = _login(service)

        assert identity.codes == ["code"]
        assert result.user.username == USERNAME
        assert result.claim_outcome is None
        assert result.session_id == "session_01"
        assert not users.created

    def test_creates_missing_user_in_transaction(self):
        users = FakeUsers()
        transaction = FakeTransaction()
        identity = FakeIdentity(
            _identity(email="new@example.com", name="New", avatar_url="https://a/b")
        )
        service = _service(users=users, transaction=transaction, identity=identity)

        result = _login(service)

        assert transaction.savepoints == 1
        assert users.created == [
            {
                "slug": "user_01me",
                "username": USERNAME,
                "email": "new@example.com",
                "avatar_url": "https://a/b",
                "name": "New",
            }
        ]
        assert result.user.username == USERNAME

    def test_create_strips_duplicate_email(self):
        users = FakeUsers(existing_emails={"taken@example.com"})
        identity = FakeIdentity(_identity(email="taken@example.com"))
        service = _service(users=users, identity=identity)

        _login(service)

        assert not users.created[0]["email"]

    def test_converted_claim_returns_claimed_user(self):
        claimed = _user_dto(slug="kid", username="connected|kid")
        users = FakeUsers(users=[claimed])
        claims = FakeClaims(
            ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug="kid")
        )
        service = _service(users=users, claims=claims)

        result = _login(service, claim_token="token")

        assert claims.redeemed == [("token", USERNAME)]
        assert result.claim_outcome == ClaimOutcome.CONVERTED
        assert result.user.slug == "kid"
        assert not users.created

    def test_failed_claim_keeps_existing_account(self):
        users = FakeUsers(users=[_user_dto()])
        claims = FakeClaims(ClaimResultDTO(outcome=ClaimOutcome.ALREADY_AUTHENTICATED))
        service = _service(users=users, claims=claims)

        result = _login(service, claim_token="token")

        assert result.claim_outcome == ClaimOutcome.ALREADY_AUTHENTICATED
        assert result.user.username == USERNAME

    def test_no_claim_token_skips_redemption(self):
        claims = FakeClaims()
        service = _service(users=FakeUsers(users=[_user_dto()]), claims=claims)

        _login(service)

        assert not claims.redeemed

    def test_concurrent_insert_is_adopted(self):
        # read_by_username misses, then create raises the unique-constraint
        # error because a concurrent callback already inserted the row; the
        # service swallows it and re-reads the now-present user.
        users = _RacingUsers()
        service = _service(users=users)

        result = _login(service)

        assert result.user.username == USERNAME
        assert users.create_attempts == 1

    def test_truncates_slug_to_field_width(self):
        users = FakeUsers()
        identity = FakeIdentity(_identity(provider_user_id="user_" + "a" * 80))
        service = _service(users=users, identity=identity)

        _login(service)

        assert len(users.created[0]["slug"]) <= SLUG_MAX_LENGTH

    def test_de_collides_slug_owned_by_another_row(self):
        # A CONNECTED companion already owns the slug; the new ACTIVE account
        # must get a different, non-colliding slug rather than fail the insert.
        users = FakeUsers(users=[_user_dto(slug="user_01me", username="connected|x")])
        service = _service(users=users)

        _login(service)

        assert users.created[0]["slug"] != "user_01me"

    def test_unadoptable_constraint_error_surfaces(self):
        # The insert fails and no row can be read back, so the real database
        # error must propagate instead of a bare NotFoundError.
        service = _service(users=_RacingUsers(misses=math.inf))

        with pytest.raises(DatabaseConstraintError):
            _login(service)


class TestSyncIdentity:
    def test_updates_in_transaction_and_returns_fresh_user(self):
        users = FakeUsers(users=[_user_dto(name="")])
        transaction = FakeTransaction()
        identity = FakeIdentity(_identity(name="New Name"))
        service = _service(users=users, transaction=transaction, identity=identity)

        result = _login(service)

        assert transaction.entered == 1
        assert users.updated == [("me", {"name": "New Name"})]
        assert result.user.name == "New Name"

    def test_drops_colliding_email_but_applies_rest(self):
        users = FakeUsers(
            users=[_user_dto(name="")], existing_emails={"taken@example.com"}
        )
        identity = FakeIdentity(_identity(email="taken@example.com", name="New Name"))
        service = _service(users=users, identity=identity)

        _login(service)

        assert users.updated == [("me", {"name": "New Name"})]

    def test_nothing_new_skips_update(self):
        users = FakeUsers(users=[_user_dto(name="Me", email="me@example.com")])
        identity = FakeIdentity(_identity(email="me@example.com", name="Other"))
        service = _service(users=users, identity=identity)

        _login(service)

        assert not users.updated

    def test_overlong_avatar_is_dropped(self):
        users = FakeUsers(users=[_user_dto(avatar_url="https://old")])
        long_url = "https://a/" + "x" * MAX_AVATAR_URL_LENGTH
        identity = FakeIdentity(_identity(avatar_url=long_url))
        service = _service(users=users, identity=identity)

        _login(service)

        assert not users.updated


class TestLegacyLinking:
    def test_external_id_links_auth0_account(self):
        legacy = _user_dto(slug="old", username="auth0|google-oauth2|1")
        users = FakeUsers(users=[legacy])
        transaction = FakeTransaction()
        identity = FakeIdentity(_identity(legacy_id="google-oauth2|1"))
        service = _service(users=users, transaction=transaction, identity=identity)

        result = _login(service)

        assert users.updated == [("old", {"username": USERNAME})]
        assert transaction.entered == 1
        assert result.user.slug == "old"
        assert not users.created

    def test_verified_email_links_auth0_account(self):
        legacy = _user_dto(slug="old", username="auth0|x", email="me@example.com")
        users = FakeUsers(users=[legacy])
        identity = FakeIdentity(_identity(email="Me@Example.com"))
        service = _service(users=users, identity=identity)

        result = _login(service)

        assert result.user.slug == "old"
        assert result.user.username == USERNAME

    @pytest.mark.parametrize(
        ("username", "verified"),
        (("auth0|x", False), ("workos|user_OTHER", True), ("connected|x", True)),
    )
    def test_email_does_not_link_otherwise(self, username, verified):
        other = _user_dto(slug="other", username=username, email="me@example.com")
        users = FakeUsers(users=[other])
        identity = FakeIdentity(
            _identity(email="me@example.com", email_verified=verified)
        )
        service = _service(users=users, identity=identity)

        result = _login(service)

        assert result.user.slug != "other"
        assert users.created[0]["username"] == USERNAME

    def test_missing_import_link_does_not_fall_back_to_email(self):
        other = _user_dto(slug="other", username="auth0|x", email="me@example.com")
        users = FakeUsers(users=[other])
        identity = FakeIdentity(
            _identity(legacy_id="deleted-in-auth0", email="me@example.com")
        )
        service = _service(users=users, identity=identity)

        result = _login(service)

        assert result.user.slug != "other"
        assert users.created[0]["username"] == USERNAME

    def test_whole_login_runs_in_one_transaction(self):
        legacy = _user_dto(slug="old", username="auth0|abc", name="")
        users = FakeUsers(users=[legacy])
        transaction = FakeTransaction()
        identity = FakeIdentity(_identity(legacy_id="abc", name="New Name"))
        service = _service(users=users, transaction=transaction, identity=identity)

        _login(service)

        assert transaction.entered == 1
        assert users.updated == [
            ("old", {"username": USERNAME}),
            ("old", {"name": "New Name"}),
        ]

    def test_linked_account_is_already_authenticated_for_claims(self):
        legacy = _user_dto(slug="old", username="auth0|abc")
        users = FakeUsers(users=[legacy])
        claims = FakeClaims(ClaimResultDTO(outcome=ClaimOutcome.ALREADY_AUTHENTICATED))
        identity = FakeIdentity(_identity(legacy_id="abc"))
        service = _service(users=users, claims=claims, identity=identity)

        result = _login(service, claim_token="token")

        assert users.updated[0] == ("old", {"username": USERNAME})
        assert claims.redeemed == [("token", USERNAME)]
        assert result.user.slug == "old"
