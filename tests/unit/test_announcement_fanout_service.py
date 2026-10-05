from contextlib import contextmanager

from ludamus.mills.notifications import AnnouncementFanoutService
from ludamus.pacts.notifications import ClaimedAnnouncementDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()


def _claimed(pk, *, sphere_id=1):
    return ClaimedAnnouncementDTO(
        pk=pk, sphere_id=sphere_id, title=f"title-{pk}", content=f"content-{pk}"
    )


class FakeRepo:
    def __init__(self, *, claimable=(), subscribers=(), due=()):
        self._claimable = {a.pk: a for a in claimable}
        self._subscribers = list(subscribers)
        self._due = list(due)
        self.created = []

    def claim(self, announcement_id):
        return self._claimable.pop(announcement_id, None)

    def due_ids(self):
        return list(self._due)

    def active_sphere_subscriber_ids(self, sphere_id):
        return list(self._subscribers)

    def create_announcement_notifications(self, *, recipient_ids, announcement):
        self.created.append((recipient_ids, announcement))
        return len(recipient_ids)


class TestFanout:
    def test_claimed_announcement_notifies_subscribers(self):
        announcement = _claimed(5)
        subscribers = [7, 8]
        repo = FakeRepo(claimable=[announcement], subscribers=subscribers)
        transaction = FakeTransaction()
        service = AnnouncementFanoutService(transaction, repo)

        notified = service.fanout(5)

        assert notified == len(subscribers)
        assert transaction.entered == 1
        assert repo.created == [(subscribers, announcement)]

    def test_unclaimable_announcement_writes_nothing(self):
        repo = FakeRepo()
        service = AnnouncementFanoutService(FakeTransaction(), repo)

        assert service.fanout(5) == 0
        assert not repo.created

    def test_fanout_due_processes_every_due_announcement(self):
        claimable_ids = [1, 2]
        repo = FakeRepo(
            claimable=[_claimed(pk) for pk in claimable_ids],
            subscribers=[7],
            due=[*claimable_ids, 3],
        )
        service = AnnouncementFanoutService(FakeTransaction(), repo)

        notified = service.fanout_due()

        assert notified == len(claimable_ids)
        assert [announcement.pk for _, announcement in repo.created] == claimable_ids
