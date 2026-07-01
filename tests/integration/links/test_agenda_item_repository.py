from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ludamus.adapters.db.django.models import AgendaItem, Session
from ludamus.adapters.db.django.repositories import DjangoAgendaItemRepository

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import Event, Space


@pytest.fixture
def repo() -> DjangoAgendaItemRepository:
    return DjangoAgendaItemRepository()


@pytest.fixture
def session_factory(event: Event) -> callable:
    def _make(*, title: str = "Test Session", slug: str = "test-session") -> Session:
        return Session.objects.create(
            event=event,
            display_name="Presenter",
            title=title,
            slug=slug,
            description="A session",
            participants_limit=10,
            min_age=0,
        )

    return _make


@pytest.mark.django_db
class TestDjangoAgendaItemRepository:
    def test_get_by_space_and_time_range_returns_overlapping_items(
        self,
        repo: DjangoAgendaItemRepository,
        space_factory: callable,
        session_factory: callable,
        event: Event,
    ) -> None:
        space = space_factory()
        session = session_factory()
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItem.objects.create(
            space=space,
            session=session,
            session_confirmed=True,
            start_time=start,
            end_time=end,
        )

        items = repo.get_by_space_and_time_range(
            space_id=space.pk, start_time=start, end_time=end
        )

        assert len(items) == 1
        assert items[0].session_id == session.pk

    def test_get_by_space_and_time_range_excludes_non_overlapping(
        self,
        repo: DjangoAgendaItemRepository,
        space_factory: callable,
        session_factory: callable,
        event: Event,
    ) -> None:
        space = space_factory()
        session = session_factory()
        start = event.start_time
        AgendaItem.objects.create(
            space=space,
            session=session,
            session_confirmed=True,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        later_start = start + timedelta(hours=2)
        items = repo.get_by_space_and_time_range(
            space_id=space.pk,
            start_time=later_start,
            end_time=later_start + timedelta(hours=1),
        )

        assert items == []

    def test_get_by_space_and_time_range_excludes_other_spaces(
        self,
        repo: DjangoAgendaItemRepository,
        space_factory: callable,
        session_factory: callable,
        event: Event,
    ) -> None:
        space_a = space_factory(name="A", slug="a")
        space_b = space_factory(name="B", slug="b")
        session = session_factory()
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItem.objects.create(
            space=space_a,
            session=session,
            session_confirmed=True,
            start_time=start,
            end_time=end,
        )

        items = repo.get_by_space_and_time_range(
            space_id=space_b.pk, start_time=start, end_time=end
        )

        assert items == []

    def test_get_by_space_and_time_range_excludes_unconfirmed(
        self,
        repo: DjangoAgendaItemRepository,
        space_factory: callable,
        session_factory: callable,
        event: Event,
    ) -> None:
        space = space_factory()
        session = session_factory()
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItem.objects.create(
            space=space,
            session=session,
            session_confirmed=False,
            start_time=start,
            end_time=end,
        )

        items = repo.get_by_space_and_time_range(
            space_id=space.pk, start_time=start, end_time=end
        )

        assert items == []

    def test_get_by_space_and_time_range_partial_overlap_start(
        self,
        repo: DjangoAgendaItemRepository,
        space_factory: callable,
        session_factory: callable,
        event: Event,
    ) -> None:
        space = space_factory()
        session = session_factory()
        start = event.start_time
        AgendaItem.objects.create(
            space=space,
            session=session,
            session_confirmed=True,
            start_time=start,
            end_time=start + timedelta(hours=2),
        )

        items = repo.get_by_space_and_time_range(
            space_id=space.pk,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=3),
        )

        assert len(items) == 1

    def test_get_by_space_and_time_range_partial_overlap_end(
        self,
        repo: DjangoAgendaItemRepository,
        space_factory: callable,
        session_factory: callable,
        event: Event,
    ) -> None:
        space = space_factory()
        session = session_factory()
        start = event.start_time
        AgendaItem.objects.create(
            space=space,
            session=session,
            session_confirmed=True,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=3),
        )

        items = repo.get_by_space_and_time_range(
            space_id=space.pk,
            start_time=start,
            end_time=start + timedelta(hours=2),
        )

        assert len(items) == 1

    def test_get_by_space_and_time_range_adjacent_not_overlapping(
        self,
        repo: DjangoAgendaItemRepository,
        space_factory: callable,
        session_factory: callable,
        event: Event,
    ) -> None:
        space = space_factory()
        session = session_factory()
        start = event.start_time
        AgendaItem.objects.create(
            space=space,
            session=session,
            session_confirmed=True,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        items = repo.get_by_space_and_time_range(
            space_id=space.pk,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=2),
        )

        assert items == []
