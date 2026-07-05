from contextlib import contextmanager

from ludamus.mills.bookmarks import BookmarkService


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
    def __init__(self, *, toggle_result=True, bookmarked_ids=None):
        self._toggle_result = toggle_result
        self._bookmarked_ids = set(bookmarked_ids or set())
        self.toggle_calls = []
        self.bookmarked_calls = []

    def toggle(self, *, user_id, session_id, sphere_id):
        self.toggle_calls.append((user_id, session_id, sphere_id))
        return self._toggle_result

    def bookmarked_session_ids(self, *, user_id, event_id):
        self.bookmarked_calls.append((user_id, event_id))
        return self._bookmarked_ids


def test_toggle_runs_in_transaction_and_returns_repo_state():
    repo = FakeRepo(toggle_result=False)
    transaction = FakeTransaction()
    service = BookmarkService(transaction, repo)

    result = service.toggle(user_id=7, session_id=42, sphere_id=3)

    assert result is False
    assert transaction.entered == 1
    assert repo.toggle_calls == [(7, 42, 3)]


def test_toggle_passes_through_missing_session_state():
    repo = FakeRepo(toggle_result=None)
    service = BookmarkService(FakeTransaction(), repo)

    result = service.toggle(user_id=7, session_id=42, sphere_id=3)

    assert result is None


def test_bookmarked_session_ids_delegates_without_transaction():
    repo = FakeRepo(bookmarked_ids={1, 3})
    transaction = FakeTransaction()
    service = BookmarkService(transaction, repo)

    result = service.bookmarked_session_ids(user_id=7, event_id=11)

    assert result == {1, 3}
    assert transaction.entered == 0
    assert repo.bookmarked_calls == [(7, 11)]
