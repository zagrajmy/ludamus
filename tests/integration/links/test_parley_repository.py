from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.models import EventBan, Facilitator
from ludamus.links.db.django.parley import ParleyRepository
from ludamus.pacts import SessionParticipationStatus, SessionStatus
from ludamus.pacts.parley import ParleyTimeWindow
from ludamus.specs.parley import (
    PARLEY_SESSION_READ_ONLY_DELAY,
    PARLEY_SESSION_RETENTION,
)
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SessionParticipationFactory,
    SphereFactory,
)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 6, 12, tzinfo=UTC)


@pytest.fixture
def window(now: datetime) -> ParleyTimeWindow:
    return ParleyTimeWindow(
        now=now,
        retained_after=now - PARLEY_SESSION_RETENTION,
        writable_after=now - PARLEY_SESSION_READ_ONLY_DELAY,
        read_only_delay=PARLEY_SESSION_READ_ONLY_DELAY,
        retention=PARLEY_SESSION_RETENTION,
    )


def test_returns_only_confirmed_and_facilitated_sessions(
    sphere, active_user, now, window
):
    sphere.parley_enabled = True
    sphere.save()
    event = EventFactory(
        sphere=sphere,
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(days=1),
    )
    confirmed = SessionFactory(
        event=event, category=None, title="Confirmed", status=SessionStatus.ACCEPTED
    )
    SessionParticipationFactory(
        session=confirmed, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )
    waiting = SessionFactory(event=event, category=None, title="Waiting")
    SessionParticipationFactory(
        session=waiting, user=active_user, status=SessionParticipationStatus.WAITING
    )
    offered = SessionFactory(event=event, category=None, title="Offered")
    SessionParticipationFactory(
        session=offered, user=active_user, status=SessionParticipationStatus.OFFERED
    )
    facilitated = SessionFactory(event=event, category=None, title="Facilitated")
    facilitator = Facilitator.objects.create(
        event=event, user=active_user, display_name=active_user.name, slug="ada"
    )
    facilitated.facilitators.add(facilitator)

    access = ParleyRepository().read_access(
        sphere_id=sphere.pk, user_id=active_user.pk, window=window
    )

    assert access is not None
    assert [(room.title, room.can_write) for room in access.rooms] == [
        (sphere.name, True),
        ("Confirmed", True),
        ("Facilitated", False),
    ]


def test_manager_sees_unbanned_unexpired_sessions_only(
    sphere, active_user, now, window
):
    sphere.parley_enabled = True
    sphere.save()
    sphere.managers.add(active_user)
    event = EventFactory(
        sphere=sphere,
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=1),
    )
    readable = SessionFactory(
        event=event, category=None, title="Readable", status=SessionStatus.ACCEPTED
    )
    banned_event = EventFactory(sphere=sphere)
    SessionFactory(event=banned_event, category=None, title="Banned")
    EventBan.objects.create(event=banned_event, user=active_user)
    expired_event = EventFactory(
        sphere=sphere,
        publication_time=now - timedelta(days=41),
        start_time=now - timedelta(days=40),
        end_time=now - timedelta(days=31),
    )
    SessionFactory(event=expired_event, category=None, title="Expired")
    SessionFactory(
        event=EventFactory(sphere=SphereFactory()), category=None, title="Foreign"
    )

    access = ParleyRepository().read_access(
        sphere_id=sphere.pk, user_id=active_user.pk, window=window
    )

    assert access is not None
    assert [room.title for room in access.rooms] == [sphere.name, readable.title]
    assert access.rooms[1].can_write is True
    assert access.moderated_room_ids == [room.id for room in access.rooms]


@pytest.mark.parametrize("attribute", ("parley_enabled", "is_active", "user_type"))
def test_denies_disabled_or_inactive_accounts(sphere, active_user, window, attribute):
    sphere.parley_enabled = True
    sphere.save()
    if attribute == "parley_enabled":
        sphere.parley_enabled = False
        sphere.save()
    elif attribute == "is_active":
        active_user.is_active = False
        active_user.save()
    else:
        active_user.user_type = "connected"
        active_user.save()

    access = ParleyRepository().read_access(
        sphere_id=sphere.pk, user_id=active_user.pk, window=window
    )

    assert access is None
