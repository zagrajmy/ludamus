from ludamus.mills.bookmarks import BookmarkService
from ludamus.pacts.bookmarks import BookmarkStateDTO
from tests.unit.factories import FakeTransaction


class FakeBookmarks:
    # (user_id, session_id) pairs; every session belongs to event 1.
    def __init__(self, marked=()):
        self.marked = set(marked)

    def toggle(self, *, user_id, session_id, sphere_id):
        del sphere_id
        self.marked ^= {(user_id, session_id)}
        return self.session_state(user_id=user_id, session_id=session_id, event_id=1)

    def bookmarked_session_ids(self, *, user_id, event_id):
        del event_id
        return {session for user, session in self.marked if user == user_id}

    def bookmark_counts(self, *, event_id):
        del event_id
        counts: dict[int, int] = {}
        for _user, session in self.marked:
            counts[session] = counts.get(session, 0) + 1
        return counts

    def session_state(self, *, user_id, session_id, event_id):
        del event_id
        return BookmarkStateDTO(
            bookmarked=(user_id, session_id) in self.marked,
            count=sum(1 for _user, session in self.marked if session == session_id),
        )


def _service(repo):
    return BookmarkService(FakeTransaction(), repo)


class TestBookmarkService:
    def test_toggle_adds_then_removes_the_bookmark(self):
        repo = FakeBookmarks()
        service = _service(repo)

        added = service.toggle(user_id=1, session_id=7, sphere_id=3)
        removed = service.toggle(user_id=1, session_id=7, sphere_id=3)

        assert added == BookmarkStateDTO(bookmarked=True, count=1)
        assert removed == BookmarkStateDTO(bookmarked=False, count=0)
        assert not repo.marked

    def test_reads_ids_counts_and_state_for_the_event(self):
        service = _service(FakeBookmarks(marked=[(1, 7), (2, 7), (1, 8)]))

        assert service.bookmarked_session_ids(user_id=1, event_id=1) == {7, 8}
        assert service.bookmark_counts(event_id=1) == {7: 2, 8: 1}
        assert service.session_state(
            user_id=None, session_id=7, event_id=1
        ) == BookmarkStateDTO(bookmarked=False, count=2)
