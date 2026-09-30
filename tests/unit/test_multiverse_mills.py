from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from ludamus.mills.multiverse import (
    AnnouncementsService,
    ConnectionsService,
    SitesService,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.legacy import SiteDTO, SphereDTO
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    ConnectionDTO,
    SphereListItemDTO,
)

SPHERE_PK = 3
OTHER_SPHERE_PK = 4
_NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


class FakeAnnouncements:
    def __init__(self):
        self.rows = {}

    def _read(self, sphere_id, pk):
        row = self.rows.get(pk)
        if row is None or row.sphere_id != sphere_id:
            raise NotFoundError
        return row

    def list_for_sphere(self, sphere_id):
        return [row for row in self.rows.values() if row.sphere_id == sphere_id]

    def list_published(self, sphere_id):
        return [row for row in self.list_for_sphere(sphere_id) if row.is_published]

    def get(self, sphere_id, pk):
        return self._read(sphere_id, pk)

    def create(self, sphere_id, data):
        pk = len(self.rows) + 1
        self.rows[pk] = AnnouncementDTO(
            pk=pk,
            sphere_id=sphere_id,
            creation_time=_NOW,
            modification_time=_NOW,
            **data.model_dump(),
        )
        return self.rows[pk]

    def update(self, sphere_id, pk, data):
        row = self._read(sphere_id, pk)
        self.rows[pk] = row.model_copy(update=data.model_dump())
        return self.rows[pk]

    def delete(self, sphere_id, pk):
        self._read(sphere_id, pk)
        del self.rows[pk]


def _announcement(**overrides):
    return AnnouncementData(
        **({"title": "Hi", "content": "Body", "is_published": True} | overrides)
    )


class TestAnnouncementsService:
    @staticmethod
    def _service():
        repo = FakeAnnouncements()
        return AnnouncementsService(FakeTransaction(), repo), repo

    def test_create_then_lists_scoped_to_sphere(self):
        service, _ = self._service()
        created = service.create(SPHERE_PK, _announcement())
        service.create(OTHER_SPHERE_PK, _announcement(title="Elsewhere"))

        assert service.list_for_sphere(SPHERE_PK) == [created]
        assert created.title == "Hi"

    def test_list_published_hides_drafts(self):
        service, _ = self._service()
        published = service.create(SPHERE_PK, _announcement())
        service.create(SPHERE_PK, _announcement(is_published=False))

        assert service.list_published(SPHERE_PK) == [published]

    def test_get_is_scoped_to_sphere(self):
        service, _ = self._service()
        created = service.create(SPHERE_PK, _announcement())

        assert service.get(SPHERE_PK, created.pk) == created
        with pytest.raises(NotFoundError):
            service.get(OTHER_SPHERE_PK, created.pk)

    def test_update_changes_the_row(self):
        service, _ = self._service()
        created = service.create(SPHERE_PK, _announcement())

        updated = service.update(SPHERE_PK, created.pk, _announcement(title="New"))

        assert updated.title == "New"
        assert service.get(SPHERE_PK, created.pk).title == "New"

    def test_delete_removes_the_row(self):
        service, repo = self._service()
        created = service.create(SPHERE_PK, _announcement())

        service.delete(SPHERE_PK, created.pk)

        assert not repo.rows


class FakeConnections:
    def __init__(self):
        self.rows = {}
        self.secrets = {}

    def _read(self, sphere_id, pk):
        row = self.rows.get(pk)
        if row is None or row.sphere_id != sphere_id:
            raise NotFoundError
        return row

    def list_for_sphere(self, sphere_id):
        return [row for row in self.rows.values() if row.sphere_id == sphere_id]

    def get(self, sphere_id, pk):
        return self._read(sphere_id, pk)

    def create(self, sphere_id, display_name):
        pk = len(self.rows) + 1
        self.rows[pk] = ConnectionDTO(
            pk=pk, sphere_id=sphere_id, display_name=display_name, has_secret=False
        )
        return self.rows[pk]

    def update(self, sphere_id, pk, display_name):
        row = self._read(sphere_id, pk)
        self.rows[pk] = row.model_copy(update={"display_name": display_name})
        return self.rows[pk]

    def update_secret(self, sphere_id, pk, blob):
        self._read(sphere_id, pk)
        self.secrets[pk] = blob
        self.rows[pk] = self.rows[pk].model_copy(update={"has_secret": True})

    def delete(self, sphere_id, pk):
        self._read(sphere_id, pk)
        del self.rows[pk]


class FakeEncryptor:
    @staticmethod
    def encrypt(plaintext):
        return b"enc:" + plaintext


class TestConnectionsService:
    @staticmethod
    def _service():
        repo = FakeConnections()
        return ConnectionsService(FakeTransaction(), repo, FakeEncryptor()), repo

    def test_create_without_secret(self):
        service, repo = self._service()

        created = service.create(SPHERE_PK, "Sheets")

        assert service.list_for_sphere(SPHERE_PK) == [created]
        assert service.get(SPHERE_PK, created.pk).has_secret is False
        assert not repo.secrets

    def test_create_stores_the_encrypted_secret(self):
        service, repo = self._service()

        created = service.create(SPHERE_PK, "Sheets", b"key")

        assert repo.secrets == {created.pk: b"enc:key"}
        assert service.get(SPHERE_PK, created.pk).has_secret is True

    def test_update_name_keeps_the_secret(self):
        service, repo = self._service()
        created = service.create(SPHERE_PK, "Sheets", b"key")

        updated = service.update(SPHERE_PK, created.pk, "Renamed")

        assert updated.display_name == "Renamed"
        assert repo.secrets == {created.pk: b"enc:key"}

    def test_update_rotates_the_secret(self):
        service, repo = self._service()
        created = service.create(SPHERE_PK, "Sheets", b"key")

        service.update(SPHERE_PK, created.pk, "Sheets", b"new")

        assert repo.secrets == {created.pk: b"enc:new"}

    def test_reads_and_writes_are_scoped_to_sphere(self):
        service, repo = self._service()
        created = service.create(SPHERE_PK, "Sheets")

        with pytest.raises(NotFoundError):
            service.get(OTHER_SPHERE_PK, created.pk)
        with pytest.raises(NotFoundError):
            service.update(OTHER_SPHERE_PK, created.pk, "Stolen")
        with pytest.raises(NotFoundError):
            service.delete(OTHER_SPHERE_PK, created.pk)
        assert repo.rows[created.pk].display_name == "Sheets"

    def test_delete_removes_the_row(self):
        service, repo = self._service()
        created = service.create(SPHERE_PK, "Sheets")

        service.delete(SPHERE_PK, created.pk)

        assert not repo.rows


def _sphere(pk):
    return SphereDTO(
        name=f"Sfera {pk}",
        pk=pk,
        site=SiteDTO(domain=f"s{pk}.example.net", name="Sfera", pk=pk),
    )


class FakeSpheres:
    def __init__(self):
        self.reads = 0

    def read(self, sphere_id):
        self.reads += 1
        return _sphere(sphere_id)


class FakeDirectory:
    @staticmethod
    def list_all():
        return [SphereListItemDTO(pk=SPHERE_PK, name="Sfera", domain="s.example.net")]


class TestSitesService:
    def test_read_is_memoised_per_sphere(self):
        spheres = FakeSpheres()
        service = SitesService(spheres, FakeDirectory())

        first = service.read(SPHERE_PK)
        second = service.read(SPHERE_PK)
        other = service.read(OTHER_SPHERE_PK)

        assert first == second == _sphere(SPHERE_PK)
        assert other == _sphere(OTHER_SPHERE_PK)
        assert spheres.reads == len({SPHERE_PK, OTHER_SPHERE_PK})

    def test_list_spheres_passes_through(self):
        assert SitesService(FakeSpheres(), FakeDirectory()).list_spheres() == [
            SphereListItemDTO(pk=SPHERE_PK, name="Sfera", domain="s.example.net")
        ]
