from contextlib import contextmanager

from ludamus.mills.crowd import ClaimService
from ludamus.pacts.crowd import ClaimableProfileDTO, ClaimOutcome


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()


class FakeRepo:
    def __init__(
        self, *, token_valid=True, existing_usernames=(), converted_slug="kid"
    ):
        self._token_valid = token_valid
        self._existing = set(existing_usernames)
        self._converted_slug = converted_slug
        self.issued = []
        self.converted = []

    def issue_token(self, *, manager_slug, user_slug, token):
        self.issued.append((manager_slug, user_slug, token))
        return self._token_valid

    def read_claimable(self, token):  # noqa: ARG002
        return _claimable() if self._token_valid else None

    def username_exists(self, username):
        return username in self._existing

    def convert(self, *, token, username):
        if not self._token_valid:
            return None
        self.converted.append((token, username))
        return self._converted_slug


def _claimable(name="Kid", slug="kid", manager_name="Parent"):
    return ClaimableProfileDTO(name=name, slug=slug, manager_name=manager_name)


class TestIssue:
    def test_returns_token_and_persists_in_transaction(self):
        repo = FakeRepo(token_valid=True)
        transaction = FakeTransaction()
        service = ClaimService(transaction, repo)

        token = service.issue(manager_slug="parent", user_slug="kid")

        assert transaction.entered == 1
        assert token
        assert repo.issued == [("parent", "kid", token)]

    def test_returns_none_when_row_not_found(self):
        repo = FakeRepo(token_valid=False)
        service = ClaimService(FakeTransaction(), repo)

        assert service.issue(manager_slug="parent", user_slug="ghost") is None


class TestRedeem:
    def test_converts_managed_row_into_account(self):
        repo = FakeRepo(token_valid=True, converted_slug="kid")
        transaction = FakeTransaction()
        service = ClaimService(transaction, repo)

        result = service.redeem(token="t", username="auth0|new")

        assert transaction.entered == 1
        assert result.outcome == ClaimOutcome.CONVERTED
        assert result.user_slug == "kid"
        assert repo.converted == [("t", "auth0|new")]

    def test_refuses_when_recipient_already_has_account(self):
        repo = FakeRepo(token_valid=True, existing_usernames=["auth0|me"])
        service = ClaimService(FakeTransaction(), repo)

        result = service.redeem(token="t", username="auth0|me")

        assert result.outcome == ClaimOutcome.ALREADY_AUTHENTICATED
        assert not result.user_slug
        assert not repo.converted

    def test_invalid_when_token_unknown(self):
        repo = FakeRepo(token_valid=False)
        service = ClaimService(FakeTransaction(), repo)

        result = service.redeem(token="bad", username="auth0|new")

        assert result.outcome == ClaimOutcome.INVALID
        assert not repo.converted
