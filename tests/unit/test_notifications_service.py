from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.enrollment import NotificationsService
from ludamus.pacts.enrollment import NotificationDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


class FakeRepo:
    def __init__(self, *, unread=0, recent=None, all_items=None, open_result=None):
        self._unread = unread
        self._recent = recent or []
        self._all = all_items or []
        self._open_result = open_result
        self.marked: list[int] = []
        self.opened: list[tuple[int, int]] = []

    def unread_count(self, _user_id):
        return self._unread

    def list_recent(self, _user_id, _limit):
        return self._recent

    def list_all(self, _user_id):
        return self._all

    def mark_read_one(self, user_id, pk):
        self.opened.append((user_id, pk))
        return self._open_result

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
        repo = FakeRepo(unread=expected_unread, recent=[_item(1), _item(2)])
        service = NotificationsService(FakeTransaction(), repo)

        result = service.get_navbar(7)

        assert result.unread_count == expected_unread
        assert [i.pk for i in result.items] == [1, 2]

    def test_mark_all_read_delegates_in_transaction(self):
        repo = FakeRepo(unread=0, recent=[])
        service = NotificationsService(FakeTransaction(), repo)

        service.mark_all_read(7)

        assert repo.marked == [7]

    def test_list_for_user_returns_full_history(self):
        repo = FakeRepo(all_items=[_item(3), _item(2), _item(1)])
        service = NotificationsService(FakeTransaction(), repo)

        result = service.list_for_user(7)

        assert [i.pk for i in result] == [3, 2, 1]

    def test_open_marks_read_and_returns_notification(self):
        opened = _item(5)
        repo = FakeRepo(open_result=opened)
        service = NotificationsService(FakeTransaction(), repo)

        result = service.open(7, 5)

        assert result is opened
        assert repo.opened == [(7, 5)]

    def test_open_returns_none_for_foreign_notification(self):
        repo = FakeRepo(open_result=None)
        service = NotificationsService(FakeTransaction(), repo)

        result = service.open(7, 999)

        assert result is None
        assert repo.opened == [(7, 999)]
