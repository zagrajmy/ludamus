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
    def __init__(self, *, claimable=None, existing_usernames=(), converted_slug="kid"):
        self._claimable = claimable
        self._existing = set(existing_usernames)
        self._converted_slug = converted_slug
        self.issued = []
        self.converted = []

    def issue_token(self, *, manager_slug, user_slug, token):
        self.issued.append((manager_slug, user_slug, token))
        return self._claimable is not None

    def read_claimable(self, token):  # noqa: ARG002
        return self._claimable

    def username_exists(self, username):
        return username in self._existing

    def convert(self, *, token, username, email, avatar_url):
        self.converted.append((token, username, email, avatar_url))
        return self._converted_slug


def _claimable(name="Kid", slug="kid", manager_name="Parent"):
    return ClaimableProfileDTO(name=name, slug=slug, manager_name=manager_name)


class TestIssue:
    def test_returns_token_and_persists_in_transaction(self):
        repo = FakeRepo(claimable=_claimable())
        transaction = FakeTransaction()
        service = ClaimService(transaction, repo)

        token = service.issue(manager_slug="parent", user_slug="kid")

        assert transaction.entered == 1
        assert token
        assert repo.issued == [("parent", "kid", token)]

    def test_returns_none_when_row_not_found(self):
        repo = FakeRepo(claimable=None)
        service = ClaimService(FakeTransaction(), repo)

        assert service.issue(manager_slug="parent", user_slug="ghost") is None


class TestRedeem:
    def test_converts_managed_row_into_account(self):
        repo = FakeRepo(claimable=_claimable(), converted_slug="kid")
        transaction = FakeTransaction()
        service = ClaimService(transaction, repo)

        result = service.redeem(
            token="t", username="auth0|new", email="k@example.com", avatar_url="pic"
        )

        assert transaction.entered == 1
        assert result.outcome == ClaimOutcome.CONVERTED
        assert result.user_slug == "kid"
        assert repo.converted == [("t", "auth0|new", "k@example.com", "pic")]

    def test_refuses_when_recipient_already_has_account(self):
        repo = FakeRepo(claimable=_claimable(), existing_usernames=["auth0|me"])
        service = ClaimService(FakeTransaction(), repo)

        result = service.redeem(token="t", username="auth0|me", email="", avatar_url="")

        assert result.outcome == ClaimOutcome.ALREADY_AUTHENTICATED
        assert not result.user_slug
        assert repo.converted == []

    def test_invalid_when_token_unknown(self):
        repo = FakeRepo(claimable=None)
        service = ClaimService(FakeTransaction(), repo)

        result = service.redeem(
            token="bad", username="auth0|new", email="", avatar_url=""
        )

        assert result.outcome == ClaimOutcome.INVALID
        assert repo.converted == []
