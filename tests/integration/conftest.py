from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from django.contrib.sites.models import Site
from django.test import Client

from ludamus.adapters.db.django.models import (
    Event,
    Space,
    Sphere,
    TimeSlot,
    User,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def site() -> Site:
    return Site.objects.get_or_create(
        id=1, defaults={"domain": "testserver", "name": "Test Server"}
    )[0]


@pytest.fixture
def sphere(site: Site) -> Sphere:
    return Sphere.objects.create(site=site, name="Test Sphere")


@pytest.fixture
def event(sphere: Sphere) -> Event:
    now = datetime.now(tz=UTC)
    return Event.objects.create(
        sphere=sphere,
        name="Test Event",
        slug="test-event",
        start_time=now,
        end_time=now + timedelta(days=2),
        publication_time=now - timedelta(days=1),
    )


@pytest.fixture
def manager_user(sphere: Sphere) -> User:
    user = User.objects.create_user(
        username="manager",
        email="manager@example.com",
        password="password123",
        name="Manager User",
        slug="manager-user",
        is_staff=True,
    )
    sphere.managers.add(user)
    return user


@pytest.fixture
def regular_user() -> User:
    return User.objects.create_user(
        username="regular",
        email="regular@example.com",
        password="password123",
        name="Regular User",
        slug="regular-user",
    )


@pytest.fixture
def manager_client(client: Client, manager_user: User) -> Client:
    client.force_login(manager_user)
    return client


@pytest.fixture
def space_factory(event: Event) -> Callable[..., Space]:
    def _make(
        *,
        name: str = "Test Space",
        slug: str = "test-space",
        parent: Space | None = None,
        capacity: int | None = None,
    ) -> Space:
        return Space.objects.create(
            event=event,
            parent=parent,
            name=name,
            slug=slug,
            capacity=capacity,
        )

    return _make


@pytest.fixture
def time_slot_factory(event: Event) -> Callable[..., TimeSlot]:
    def _make(
        *, start_time: datetime | None = None, end_time: datetime | None = None
    ) -> TimeSlot:
        return TimeSlot.objects.create(
            event=event,
            start_time=start_time or event.start_time,
            end_time=end_time or (event.start_time + timedelta(hours=1)),
        )

    return _make


@pytest.fixture
def _no_op() -> Iterator[None]:
    yield
