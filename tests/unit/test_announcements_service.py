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


def _dto(pk, *, sphere_id=1, is_published=True):
    return AnnouncementDTO(
        pk=pk,
        sphere_id=sphere_id,
        title=f"title-{pk}",
        content=f"content-{pk}",
        is_published=is_published,
        creation_time=datetime(2026, 6, 16, tzinfo=UTC),
        modification_time=datetime(2026, 6, 16, tzinfo=UTC),
    )


class FakeRepo:
    def __init__(self, *, all_items=(), published=()):
        self._all = list(all_items)
        self._published = list(published)
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
        return _dto(99, sphere_id=sphere_id, is_published=data.is_published)

    def update(self, sphere_id, pk, data):
        self.updated.append((sphere_id, pk, data))
        return _dto(pk, sphere_id=sphere_id, is_published=data.is_published)

    def delete(self, sphere_id, pk):
        self.deleted.append((sphere_id, pk))


class TestAnnouncementsService:
    def test_list_for_sphere_delegates_scoped_to_sphere(self):
        repo = FakeRepo(all_items=[_dto(1), _dto(2, sphere_id=2)])
        service = AnnouncementsService(FakeTransaction(), repo)

        result = service.list_for_sphere(1)

        assert [d.pk for d in result] == [1]

    def test_list_published_delegates(self):
        repo = FakeRepo(published=[_dto(1)])
        service = AnnouncementsService(FakeTransaction(), repo)

        result = service.list_published(1)

        assert [d.pk for d in result] == [1]

    def test_get_delegates(self):
        pk = 7
        repo = FakeRepo(all_items=[_dto(pk)])
        service = AnnouncementsService(FakeTransaction(), repo)

        result = service.get(1, pk)

        assert result.pk == pk

    def test_create_runs_in_transaction(self):
        created_pk = 99
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo)
        data = AnnouncementData(title="t", content="c", is_published=True)

        result = service.create(1, data)

        assert transaction.entered == 1
        assert repo.created == [(1, data)]
        assert result.pk == created_pk

    def test_update_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo)
        data = AnnouncementData(title="t", content="c", is_published=False)

        result = service.update(1, pk, data=data)

        assert transaction.entered == 1
        assert repo.updated == [(1, pk, data)]
        assert result.pk == pk

    def test_delete_runs_in_transaction(self):
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo)

        service.delete(1, 5)

        assert transaction.entered == 1
        assert repo.deleted == [(1, 5)]
