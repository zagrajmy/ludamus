from datetime import UTC, datetime, timedelta

from ludamus.mills.notifications import NAVBAR_LIMIT, NotificationsService
from ludamus.pacts.notifications import NotificationDTO
from tests.unit.factories import FakeTransaction

NOW = datetime(2026, 6, 4, 12, tzinfo=UTC)
USER_ID = 1


def _notification(pk, *, is_read=False):
    return NotificationDTO(
        pk=pk,
        kind="sphere_event_published",
        title=f"Notification {pk}",
        body="",
        url=f"/n/{pk}",
        creation_time=NOW - timedelta(minutes=pk),
        is_read=is_read,
    )


class FakeNotifications:
    def __init__(self, rows):
        # Newest first, all owned by USER_ID.
        self.rows = {row.pk: row for row in rows}

    def _owned(self, user_id):
        return list(self.rows.values()) if user_id == USER_ID else []

    def unread_count(self, user_id):
        return sum(1 for row in self._owned(user_id) if not row.is_read)

    def total_count(self, user_id):
        return len(self._owned(user_id))

    def list_for_user(self, user_id, *, limit, offset=0):
        return self._owned(user_id)[offset : offset + limit]

    def mark_read(self, user_id, pk):
        row = self.rows.get(pk)
        if row is None or user_id != USER_ID:
            return None
        self.rows[pk] = row.model_copy(update={"is_read": True})
        return self.rows[pk]

    def mark_all_read(self, user_id):
        assert user_id == USER_ID
        self.rows = {
            pk: row.model_copy(update={"is_read": True})
            for pk, row in self.rows.items()
        }


def _service(repo):
    return NotificationsService(FakeTransaction(), repo)


class TestNotificationsService:
    def test_navbar_caps_the_list_and_counts_every_unread(self):
        repo = FakeNotifications([_notification(pk) for pk in range(1, 15)])

        navbar = _service(repo).get_navbar(USER_ID)

        assert navbar.unread_count == len(repo.rows)
        assert [item.pk for item in navbar.items] == list(range(1, NAVBAR_LIMIT + 1))

    def test_history_pages_by_limit_and_offset(self):
        repo = FakeNotifications([_notification(pk) for pk in range(1, 6)])
        service = _service(repo)

        assert service.total_count(USER_ID) == len(repo.rows)
        assert [n.pk for n in service.list_for_user(USER_ID, limit=2)] == [1, 2]
        assert [n.pk for n in service.list_for_user(USER_ID, limit=2, offset=2)] == [
            3,
            4,
        ]

    def test_mark_read_flips_one_row_and_returns_it(self):
        repo = FakeNotifications([_notification(1), _notification(2)])

        marked = _service(repo).mark_read(USER_ID, 2)

        assert marked is not None
        assert marked.is_read
        assert not repo.rows[1].is_read

    def test_mark_read_of_a_foreign_row_changes_nothing(self):
        repo = FakeNotifications([_notification(1)])

        assert _service(repo).mark_read(USER_ID + 1, 1) is None
        assert not repo.rows[1].is_read

    def test_mark_all_read_flips_every_row(self):
        repo = FakeNotifications([_notification(1), _notification(2)])

        _service(repo).mark_all_read(USER_ID)

        assert all(row.is_read for row in repo.rows.values())
