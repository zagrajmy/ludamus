from __future__ import annotations

import pytest

from ludamus.adapters.db.django.repositories import (
    DjangoEventRepository,
    DjangoSessionRepository,
    DjangoSpaceRepository,
    DjangoSphereRepository,
    DjangoTimeSlotRepository,
    DjangoUserRepository,
)
from ludamus.pacts.legacy import NotFoundError


@pytest.mark.django_db
class TestRepositoriesNotFound:
    def test_event_repository_get_by_id_raises_not_found(self) -> None:
        repo = DjangoEventRepository()

        with pytest.raises(NotFoundError):
            repo.get_by_id(999_999)

    def test_event_repository_get_by_slug_raises_not_found(self) -> None:
        repo = DjangoEventRepository()

        with pytest.raises(NotFoundError):
            repo.get_by_slug("nonexistent-slug")

    def test_space_repository_get_by_id_raises_not_found(self) -> None:
        repo = DjangoSpaceRepository()

        with pytest.raises(NotFoundError):
            repo.get_by_id(999_999)

    def test_sphere_repository_get_by_id_raises_not_found(self) -> None:
        repo = DjangoSphereRepository()

        with pytest.raises(NotFoundError):
            repo.get_by_id(999_999)

    def test_time_slot_repository_get_by_id_raises_not_found(self) -> None:
        repo = DjangoTimeSlotRepository()

        with pytest.raises(NotFoundError):
            repo.get_by_id(999_999)

    def test_session_repository_get_by_id_raises_not_found(self) -> None:
        repo = DjangoSessionRepository()

        with pytest.raises(NotFoundError):
            repo.get_by_id(999_999)

    def test_user_repository_get_by_id_raises_not_found(self) -> None:
        repo = DjangoUserRepository()

        with pytest.raises(NotFoundError):
            repo.get_by_id(999_999)
