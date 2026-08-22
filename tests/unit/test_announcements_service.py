from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ludamus.mills.multiverse import AnnouncementsService
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    AnnouncementScope,
)

SPHERE = AnnouncementScope(sphere_id=1)
OTHER_SPHERE = AnnouncementScope(sphere_id=2)
EVENT = AnnouncementScope(event_id=1)


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()


def _dto(pk, *, scope=SPHERE, is_published=True):
    return AnnouncementDTO(
        pk=pk,
        sphere_id=scope.sphere_id,
        event_id=scope.event_id,
        title=f"title-{pk}",
        content=f"content-{pk}",
        is_published=is_published,
        creation_time=datetime(2026, 6, 16, tzinfo=UTC),
        modification_time=datetime(2026, 6, 16, tzinfo=UTC),
    )


def _scope_of(dto):
    return AnnouncementScope(sphere_id=dto.sphere_id, event_id=dto.event_id)


class FakeRepo:
    def __init__(self, *, all_items=(), published=()):
        self._all = list(all_items)
        self._published = list(published)
        self.created = []
        self.updated = []
        self.deleted = []

    def list_for_scope(self, scope):
        return [d for d in self._all if _scope_of(d) == scope]

    def list_published(self, scope):
        return [d for d in self._published if _scope_of(d) == scope]

    def get(self, scope, pk):
        return next(d for d in self._all if _scope_of(d) == scope and d.pk == pk)

    def create(self, scope, data):
        self.created.append((scope, data))
        return _dto(99, scope=scope, is_published=data.is_published)

    def update(self, scope, pk, data):
        self.updated.append((scope, pk, data))
        return _dto(pk, scope=scope, is_published=data.is_published)

    def delete(self, scope, pk):
        self.deleted.append((scope, pk))


class TestAnnouncementsService:
    def test_list_for_scope_delegates_scoped(self):
        repo = FakeRepo(all_items=[_dto(1), _dto(2, scope=OTHER_SPHERE)])
        service = AnnouncementsService(FakeTransaction(), repo)

        result = service.list_for_scope(SPHERE)

        assert [d.pk for d in result] == [1]

    def test_list_for_scope_separates_event_from_sphere(self):
        repo = FakeRepo(all_items=[_dto(1), _dto(2, scope=EVENT)])
        service = AnnouncementsService(FakeTransaction(), repo)

        result = service.list_for_scope(EVENT)

        assert [d.pk for d in result] == [2]

    def test_list_published_delegates(self):
        repo = FakeRepo(published=[_dto(1)])
        service = AnnouncementsService(FakeTransaction(), repo)

        result = service.list_published(SPHERE)

        assert [d.pk for d in result] == [1]

    def test_get_delegates(self):
        pk = 7
        repo = FakeRepo(all_items=[_dto(pk)])
        service = AnnouncementsService(FakeTransaction(), repo)

        result = service.get(SPHERE, pk)

        assert result.pk == pk

    def test_create_runs_in_transaction(self):
        created_pk = 99
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo)
        data = AnnouncementData(title="t", content="c", is_published=True)

        result = service.create(EVENT, data)

        assert transaction.entered == 1
        assert repo.created == [(EVENT, data)]
        assert result.pk == created_pk

    def test_update_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo)
        data = AnnouncementData(title="t", content="c", is_published=False)

        result = service.update(SPHERE, pk, data)

        assert transaction.entered == 1
        assert repo.updated == [(SPHERE, pk, data)]
        assert result.pk == pk

    def test_delete_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = AnnouncementsService(transaction, repo)

        service.delete(SPHERE, pk)

        assert transaction.entered == 1
        assert repo.deleted == [(SPHERE, pk)]


class TestAnnouncementScope:
    @pytest.mark.parametrize(
        "kwargs", ({}, {"sphere_id": 1, "event_id": 1}), ids=["neither", "both"]
    )
    def test_rejects_scope_without_exactly_one_owner(self, kwargs):
        with pytest.raises(ValidationError):
            AnnouncementScope(**kwargs)
