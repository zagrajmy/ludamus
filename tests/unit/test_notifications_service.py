from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.notifications import NAVBAR_LIMIT, NotificationsService
from ludamus.pacts.notifications import NotificationDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


class FakeRepo:
    def __init__(self, *, unread=0, total=0, rows=None, read_result=None):
        self._unread = unread
        self._total = total
        self._rows = rows or []
        self._read_result = read_result
        self.marked: list[int] = []
        self.reads: list[tuple[int, int]] = []
        self.windows: list[tuple[int, int]] = []

    def unread_count(self, _user_id):
        return self._unread

    def total_count(self, _user_id):
        return self._total

    def list_for_user(self, _user_id, *, limit, offset=0):
        self.windows.append((limit, offset))
        return self._rows[offset : offset + limit]

    def mark_read(self, user_id, pk):
        self.reads.append((user_id, pk))
        return self._read_result

    def mark_all_read(self, user_id):
        self.marked.append(user_id)


def _item(pk):
    return NotificationDTO(
        pk=pk,
        kind="waitlist_promoted",
        title=f"n-{pk}",
        body="",
        url="/x",
        creation_time=datetime(2026, 6, 4, tzinfo=UTC),
        is_read=False,
    )


class TestNotificationsService:
    def test_get_navbar_bundles_count_and_items(self):
        expected_unread = 3
        repo = FakeRepo(unread=expected_unread, rows=[_item(1), _item(2)])
        service = NotificationsService(FakeTransaction(), repo)

        result = service.get_navbar(7)

        assert result.unread_count == expected_unread
        assert [i.pk for i in result.items] == [1, 2]
        assert repo.windows == [(NAVBAR_LIMIT, 0)]

    def test_mark_all_read_delegates_in_transaction(self):
        repo = FakeRepo()
        service = NotificationsService(FakeTransaction(), repo)

        service.mark_all_read(7)

        assert repo.marked == [7]

    def test_total_count_delegates(self):
        expected_total = 42
        service = NotificationsService(
            FakeTransaction(), FakeRepo(total=expected_total)
        )

        assert service.total_count(7) == expected_total

    def test_list_for_user_passes_the_window_down(self):
        repo = FakeRepo(rows=[_item(3), _item(2), _item(1)])
        service = NotificationsService(FakeTransaction(), repo)

        result = service.list_for_user(7, limit=2, offset=1)

        assert [i.pk for i in result] == [2, 1]
        assert repo.windows == [(2, 1)]

    def test_mark_read_returns_notification(self):
        opened = _item(5)
        repo = FakeRepo(read_result=opened)
        service = NotificationsService(FakeTransaction(), repo)

        result = service.mark_read(7, 5)

        assert result is opened
        assert repo.reads == [(7, 5)]

    def test_mark_read_returns_none_for_foreign_notification(self):
        repo = FakeRepo(read_result=None)
        service = NotificationsService(FakeTransaction(), repo)

        result = service.mark_read(7, 999)

        assert result is None
        assert repo.reads == [(7, 999)]
