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
    def __init__(self, *, unread, recent):
        self._unread = unread
        self._recent = recent
        self.marked: list[int] = []

    def unread_count(self, user_id):  # noqa: ARG002
        return self._unread

    def list_recent(self, user_id, limit):  # noqa: ARG002
        return self._recent

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
