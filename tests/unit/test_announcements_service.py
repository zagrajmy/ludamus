from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.multiverse import AnnouncementsService
from ludamus.pacts.multiverse import AnnouncementData, AnnouncementDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()


def _dto(pk, *, sphere_id=1, is_published=True, notified_at=None):
    return AnnouncementDTO(
        pk=pk,
        sphere_id=sphere_id,
        title=f"title-{pk}",
        content=f"content-{pk}",
        is_published=is_published,
        notified_at=notified_at,
        creation_time=datetime(2026, 6, 16, tzinfo=UTC),
        modification_time=datetime(2026, 6, 16, tzinfo=UTC),
    )


class FakeRepo:
    def __init__(self, *, all_items=(), published=(), notified_at=None):
        self._all = list(all_items)
        self._published = list(published)
        self._notified_at = notified_at
        self.created = []
        self.updated = []
        self.deleted = []

    def list_for_sphere(self, sphere_id):
        return [d for d in self._all if d.sphere_id == sphere_id]

    def list_published(self, sphere_id):
        return [d for d in self._published if d.sphere_id == sphere_id]

    def get(self, sphere_id, pk):
        return next(d for d in self._all if d.sphere_id == sphere_id and d.pk == pk)

    def create(self, sphere_id, data):
        self.created.append((sphere_id, data))
        return _dto(
            99,
            sphere_id=sphere_id,
            is_published=data.is_published,
            notified_at=self._notified_at,
        )

    def update(self, sphere_id, pk, data):
        self.updated.append((sphere_id, pk, data))
        return _dto(
            pk,
            sphere_id=sphere_id,
            is_published=data.is_published,
            notified_at=self._notified_at,
        )

    def delete(self, sphere_id, pk):
        self.deleted.append((sphere_id, pk))


class FakeFanoutScheduler:
    def __init__(self):
        self.scheduled = []

    def schedule_fanout(self, *, announcement_id):
        self.scheduled.append(announcement_id)


class TestAnnouncementsService:
    def test_list_for_sphere_delegates_scoped_to_sphere(self):
        repo = FakeRepo(all_items=[_dto(1), _dto(2, sphere_id=2)])
        service = AnnouncementsService(FakeTransaction(), repo, FakeFanoutScheduler())

        result = service.list_for_sphere(1)

        assert [d.pk for d in result] == [1]

    def test_list_published_delegates(self):
        repo = FakeRepo(published=[_dto(1)])
        service = AnnouncementsService(FakeTransaction(), repo, FakeFanoutScheduler())

        result = service.list_published(1)

        assert [d.pk for d in result] == [1]

    def test_get_delegates(self):
        pk = 7
        repo = FakeRepo(all_items=[_dto(pk)])
        service = AnnouncementsService(FakeTransaction(), repo, FakeFanoutScheduler())

        result = service.get(1, pk)

        assert result.pk == pk

    def test_create_runs_in_transaction(self):
        created_pk = 99
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo, FakeFanoutScheduler())
        data = AnnouncementData(title="t", content="c", is_published=True)

        result = service.create(1, data)

        assert transaction.entered == 1
        assert repo.created == [(1, data)]
        assert result.pk == created_pk

    def test_create_published_schedules_fanout(self):
        fanout = FakeFanoutScheduler()
        service = AnnouncementsService(FakeTransaction(), FakeRepo(), fanout)

        result = service.create(
            1, AnnouncementData(title="t", content="c", is_published=True)
        )

        assert fanout.scheduled == [result.pk]

    def test_create_draft_schedules_nothing(self):
        fanout = FakeFanoutScheduler()
        service = AnnouncementsService(FakeTransaction(), FakeRepo(), fanout)

        service.create(1, AnnouncementData(title="t", content="c", is_published=False))

        assert not fanout.scheduled

    def test_update_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo, FakeFanoutScheduler())
        data = AnnouncementData(title="t", content="c", is_published=False)

        result = service.update(1, pk, data)

        assert transaction.entered == 1
        assert repo.updated == [(1, pk, data)]
        assert result.pk == pk

    def test_update_publishing_unnotified_schedules_fanout(self):
        pk = 5
        fanout = FakeFanoutScheduler()
        service = AnnouncementsService(FakeTransaction(), FakeRepo(), fanout)

        service.update(
            1, pk, AnnouncementData(title="t", content="c", is_published=True)
        )

        assert fanout.scheduled == [pk]

    def test_update_republishing_notified_schedules_nothing(self):
        repo = FakeRepo(notified_at=datetime(2026, 6, 16, tzinfo=UTC))
        fanout = FakeFanoutScheduler()
        service = AnnouncementsService(FakeTransaction(), repo, fanout)

        service.update(
            1, 5, AnnouncementData(title="t", content="c", is_published=True)
        )

        assert not fanout.scheduled

    def test_delete_runs_in_transaction(self):
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo, FakeFanoutScheduler())

        service.delete(1, 5)

        assert transaction.entered == 1
        assert repo.deleted == [(1, 5)]
