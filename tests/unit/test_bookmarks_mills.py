from ludamus.mills.bookmarks import BookmarkService
from ludamus.pacts.bookmarks import BookmarkStateDTO
from tests.unit.factories import FakeTransaction

EVENT_ID = 1
SPHERE_ID = 3


class FakeBookmarks:
    # (user_id, session_id) pairs; every session belongs to EVENT_ID.
    def __init__(self, marked=()):
        self.marked = set(marked)
        self.spheres = []

    def _in_event(self, event_id):
        return self.marked if event_id == EVENT_ID else set()

    def toggle(self, *, user_id, session_id, sphere_id):
        self.spheres.append(sphere_id)
        self.marked ^= {(user_id, session_id)}
        return self.session_state(
            user_id=user_id, session_id=session_id, event_id=EVENT_ID
        )

    def bookmarked_session_ids(self, *, user_id, event_id):
        return {
            session for user, session in self._in_event(event_id) if user == user_id
        }

    def bookmark_counts(self, *, event_id):
        counts: dict[int, int] = {}
        for _user, session in self._in_event(event_id):
            counts[session] = counts.get(session, 0) + 1
        return counts

    def session_state(self, *, user_id, session_id, event_id):
        marked = self._in_event(event_id)
        return BookmarkStateDTO(
            bookmarked=(user_id, session_id) in marked,
            count=sum(1 for _user, session in marked if session == session_id),
        )


def _service(repo):
    return BookmarkService(FakeTransaction(), repo)


class TestBookmarkService:
    def test_toggle_adds_then_removes_the_bookmark(self):
        repo = FakeBookmarks()
        service = _service(repo)

        added = service.toggle(user_id=1, session_id=7, sphere_id=SPHERE_ID)
        marked_after_add = set(repo.marked)
        removed = service.toggle(user_id=1, session_id=7, sphere_id=SPHERE_ID)

        assert added == BookmarkStateDTO(bookmarked=True, count=1)
        assert marked_after_add == {(1, 7)}
        assert removed == BookmarkStateDTO(bookmarked=False, count=0)
        assert not repo.marked
        assert repo.spheres == [SPHERE_ID, SPHERE_ID]

    def test_reads_ids_counts_and_state_for_the_event(self):
        service = _service(FakeBookmarks(marked=[(1, 7), (2, 7), (1, 8)]))

        assert service.bookmarked_session_ids(user_id=1, event_id=EVENT_ID) == {7, 8}
        assert service.bookmark_counts(event_id=EVENT_ID) == {7: 2, 8: 1}
        assert service.session_state(
            user_id=None, session_id=7, event_id=EVENT_ID
        ) == BookmarkStateDTO(bookmarked=False, count=2)
        assert service.session_state(
            user_id=1, session_id=7, event_id=EVENT_ID
        ) == BookmarkStateDTO(bookmarked=True, count=2)
