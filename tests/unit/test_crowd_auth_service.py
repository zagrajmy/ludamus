import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ludamus.mills.crowd import ClaimService, CrowdAuthService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    AgeBand,
    AgeBandRequiredError,
    ClaimableProfileDTO,
    ClaimOutcome,
    ClaimResultDTO,
)
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import FakeTransaction, user_dto

_TOKEN_LENGTH = 64

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO


def _user_dto(**overrides) -> UserDTO:
    return user_dto(**{"slug": "auth0user", **overrides})


class FakeUsers:
    def __init__(self, *, users=(), taken=()):
        self._users = list(users)
        # Unavailable address -> slug of the account holding or reserving it.
        self._taken = dict(taken)
        self.created = []
        self.updated = []
        self.email_checks = []
        self.checked_at = []

    def create(self, user_data):
        self.created.append(dict(user_data))
        self._users.append(
            _user_dto(
                pk=len(self._users) + 1,
                slug=user_data.get("slug", ""),
                username=user_data.get("username", ""),
                email=user_data.get("email", ""),
                email_verified=user_data.get("email_verified", False),
                name=user_data.get("name", ""),
                age_band=user_data.get("age_band", AgeBand.UNKNOWN),
            )
        )

    def read(self, slug):
        return next(user for user in self._users if user.slug == slug)

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

    def set_age_band(self, user_slug, age_band):
        previous = self.read(user_slug).age_band
        self.update(user_slug, {"age_band": age_band})
        return previous

    def email_unavailable(self, *, email, now, exclude_slug=None):
        self.email_checks.append((email, exclude_slug))
        self.checked_at.append(now)
        return email in self._taken and self._taken[email] != exclude_slug

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
        self.redeemed = []

    def redeem(self, *, token, username):
        self.redeemed.append((token, username))
        return self._result


class FakeSubscriptions:
    def __init__(self):
        self.dropped_for = []

    def unsubscribe_everywhere(self, user_id):
        self.dropped_for.append(user_id)
        return 1


class FakeSpheres:
    def __init__(self, domains=()):
        self._domains = set(domains)

    def domain_exists(self, domain):
        return domain in self._domains


def _service(*, users, claims=None, spheres=None, subscriptions=None):
    return CrowdAuthService(
        transaction=FakeTransaction(),
        users=users,
        spheres=spheres or FakeSpheres(),
        claims=claims or FakeClaims(),
        subscriptions=subscriptions or FakeSubscriptions(),
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
        assert len(token) == _TOKEN_LENGTH
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
    def test_create_strips_duplicate_email_and_reports_conflict(self):
        users = FakeUsers(taken={"taken@example.com": "other"})
        service = _service(users=users)
        before = datetime.now(UTC)

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
        assert before <= users.checked_at[0] <= datetime.now(UTC)

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

    def test_existing_user_is_returned_without_a_claim(self):
        users = FakeUsers(users=[_user_dto(username="auth0|sub")])

        result = _service(users=users).provision_user(
            username="auth0|sub", create_data={"slug": "auth0user"}
        )

        assert result.user.slug == "auth0user"
        assert result.claim_outcome is None
        assert not users.created

    def test_existing_user_still_hears_how_their_claim_went(self):
        users = FakeUsers(users=[_user_dto(username="auth0|sub")])
        claims = FakeClaims(ClaimResultDTO(outcome=ClaimOutcome.INVALID))

        result = _service(users=users, claims=claims).provision_user(
            username="auth0|sub", create_data={"slug": "auth0user"}, claim_token="x"
        )

        assert result.claim_outcome == ClaimOutcome.INVALID
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
        assert claims.redeemed == [("valid", "auth0|sub")]
        assert not users.created

    def test_converted_claim_takes_the_declared_age_range(self):
        users = FakeUsers(users=[_user_dto(slug="kid", username="auth0|sub")])
        claims = FakeClaims(
            ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug="kid")
        )

        result = _service(users=users, claims=claims).provision_user(
            username="auth0|sub",
            create_data={"slug": "other", "age_band": AgeBand.THIRTEEN_TO_FIFTEEN},
            claim_token="valid",
        )

        assert result.user.age_band == AgeBand.THIRTEEN_TO_FIFTEEN

    def test_new_account_is_created_with_the_declared_age_range(self):
        users = FakeUsers()

        result = _service(users=users).provision_user(
            username="auth0|sub",
            create_data={
                "slug": "auth0user",
                "username": "auth0|sub",
                "age_band": AgeBand.SIXTEEN_PLUS,
            },
        )

        assert result.user.age_band == AgeBand.SIXTEEN_PLUS

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
        users = FakeUsers(taken={"dup@example.com": "other"})

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

    def test_create_data_without_email_or_slug_gets_the_defaults(self):
        users = FakeUsers()

        result = _service(users=users).provision_user(
            username="auth0|sub", create_data={"username": "auth0|sub"}
        )

        assert result.user.slug == "user"
        assert not result.user.email
        assert users.email_checks == [("", None)]


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

    def test_someone_elses_email_is_not_synced(self):
        users = FakeUsers(
            users=[_user_dto(), _user_dto(slug="other", email="theirs@example.com")],
            taken={"theirs@example.com": "other"},
        )
        before = datetime.now(UTC)

        result = _service(users=users).sync_identity(
            user_slug="auth0user", data={"email": "theirs@example.com", "name": "New"}
        )

        assert users.updated == [("auth0user", {"name": "New"})]
        assert result.name == "New"
        assert not result.email
        assert before <= users.checked_at[0] <= datetime.now(UTC)

    def test_claim_without_the_flag_adopts_the_address_unverified(self):
        users = FakeUsers(users=[_user_dto()])

        _service(users=users).sync_identity(
            user_slug="auth0user", data={"email": "new@example.com"}
        )

        assert users.updated == [
            (
                "auth0user",
                {
                    "email": "new@example.com",
                    "email_verified": False,
                    "pending_email": "",
                },
            )
        ]

    def test_own_pending_address_proven_by_the_provider_is_adopted(self):
        users = FakeUsers(users=[_user_dto()], taken={"new@example.com": "auth0user"})

        _service(users=users).sync_identity(
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

    def test_nothing_left_to_sync_skips_the_write(self):
        users = FakeUsers(users=[_user_dto()], taken={"theirs@example.com": "other"})

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


class TestAgeConfirmation:
    @pytest.mark.parametrize(
        ("previous", "declared"),
        (
            (AgeBand.UNKNOWN, AgeBand.SIXTEEN_PLUS),
            (AgeBand.SIXTEEN_PLUS, AgeBand.THIRTEEN_TO_FIFTEEN),
            (AgeBand.THIRTEEN_TO_FIFTEEN, AgeBand.SIXTEEN_PLUS),
        ),
    )
    def test_an_age_change_invalidates_browser_consent(self, previous, declared):
        user = _user_dto(age_band=previous)
        users = FakeUsers(users=[user])

        _service(users=users).confirm_age(user_slug=user.slug, age_band=declared)

        assert users.read(user.slug).privacy_revision != user.privacy_revision

    def test_reconfirming_the_same_age_preserves_browser_consent(self):
        user = _user_dto(age_band=AgeBand.SIXTEEN_PLUS)
        users = FakeUsers(users=[user])

        _service(users=users).confirm_age(
            user_slug=user.slug, age_band=AgeBand.SIXTEEN_PLUS
        )

        assert users.read(user.slug).privacy_revision == user.privacy_revision

    def test_underage_account_cannot_keep_independent_access(self):
        users = FakeUsers(users=[_user_dto(age_band=AgeBand.SIXTEEN_PLUS)])

        _service(users=users).disable_underage_account("auth0user")

        user = users.read("auth0user")
        assert user.is_active is False
        assert user.age_band == AgeBand.UNKNOWN

    @pytest.mark.parametrize(
        "age_band", (AgeBand.THIRTEEN_TO_FIFTEEN, AgeBand.SIXTEEN_PLUS)
    )
    def test_confirmed_range_is_persisted(self, age_band):
        users = FakeUsers(users=[_user_dto()])

        _service(users=users).confirm_age(user_slug="auth0user", age_band=age_band)

        assert users.read("auth0user").age_band == age_band

    def test_unknown_is_not_an_age_confirmation(self):
        users = FakeUsers(users=[_user_dto()])

        with pytest.raises(AgeBandRequiredError):
            _service(users=users).confirm_age(
                user_slug="auth0user", age_band=AgeBand.UNKNOWN
            )

        assert users.read("auth0user").age_band == AgeBand.UNKNOWN

    @pytest.mark.parametrize(
        ("previous", "declared"),
        (
            (AgeBand.UNKNOWN, AgeBand.SIXTEEN_PLUS),
            (AgeBand.SIXTEEN_PLUS, AgeBand.THIRTEEN_TO_FIFTEEN),
            (AgeBand.THIRTEEN_TO_FIFTEEN, AgeBand.THIRTEEN_TO_FIFTEEN),
        ),
    )
    def test_subscriptions_need_fresh_consent_unless_already_16_plus(
        self, previous, declared
    ):
        users = FakeUsers(users=[_user_dto(pk=7, age_band=previous)])
        subscriptions = FakeSubscriptions()

        _service(users=users, subscriptions=subscriptions).confirm_age(
            user_slug="auth0user", age_band=declared
        )

        assert subscriptions.dropped_for == [7]

    def test_a_16_plus_account_reconfirming_keeps_its_subscriptions(self):
        users = FakeUsers(users=[_user_dto(age_band=AgeBand.SIXTEEN_PLUS)])
        subscriptions = FakeSubscriptions()

        _service(users=users, subscriptions=subscriptions).confirm_age(
            user_slug="auth0user", age_band=AgeBand.SIXTEEN_PLUS
        )

        assert not subscriptions.dropped_for


class TestHasAccount:
    def test_known_identity_has_an_account(self):
        service = _service(users=FakeUsers(users=[_user_dto(username="auth0|sub")]))

        assert service.has_account("auth0|sub") is True

    def test_unknown_identity_has_none(self):
        assert _service(users=FakeUsers()).has_account("auth0|sub") is False
