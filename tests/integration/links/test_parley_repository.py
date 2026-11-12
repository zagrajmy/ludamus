from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.models import EventBan, Facilitator
from ludamus.links.db.django.parley import ParleyRepository
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.parley import ParleyTimeWindow
from ludamus.pacts.sessions import SessionStatus
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


@pytest.fixture(name="now")
def _now() -> datetime:
    return datetime(2026, 8, 6, 12, tzinfo=UTC)


@pytest.fixture(name="window")
def _window(now: datetime) -> ParleyTimeWindow:
    return ParleyTimeWindow(
        now=now,
        retained_after=now - PARLEY_SESSION_RETENTION,
        writable_after=now - PARLEY_SESSION_READ_ONLY_DELAY,
    )


def _event(sphere, now, *, ended_days_ago=-1, **fields):
    end = now - timedelta(days=ended_days_ago)
    return EventFactory(
        sphere=sphere,
        publication_time=end - timedelta(days=3),
        start_time=end - timedelta(hours=10),
        end_time=end,
        **fields,
    )


def _rooms(access):
    return [(room.id, room.can_write, room.can_moderate) for room in access.rooms]


def test_a_member_has_their_events_and_programme_points_in_every_sphere(
    sphere, active_user, now, window
):
    event = _event(sphere, now, name="Bachanalia")
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
    elsewhere = SphereFactory()
    hosted_event = _event(elsewhere, now, name="Polcon")
    hosted = SessionFactory(event=hosted_event, category=None, title="Hosted")
    hosted.facilitators.add(
        Facilitator.objects.create(
            event=hosted_event,
            user=active_user,
            display_name=active_user.name,
            slug="ada",
        )
    )
    waitlist_event = _event(SphereFactory(), now, name="Waitlist only")
    offered = SessionFactory(event=waitlist_event, category=None, title="Offered")
    SessionParticipationFactory(
        session=offered, user=active_user, status=SessionParticipationStatus.OFFERED
    )
    _event(sphere, now, name="Someone else's")

    access = ParleyRepository().read_access(user_id=active_user.pk, window=window)

    assert access is not None
    assert access.managed_sphere_ids == []
    assert sorted(_rooms(access)) == sorted(
        [
            (f"event:{sphere.pk}:{event.pk}", True, False),
            (f"event:{elsewhere.pk}:{hosted_event.pk}", True, False),
            (f"event:{waitlist_event.sphere_id}:{waitlist_event.pk}", True, False),
            (f"session:{sphere.pk}:{confirmed.pk}", True, False),
            (f"session:{elsewhere.pk}:{hosted.pk}", False, False),
        ]
    )
    assert {room.ends_at for room in access.rooms} == {int(event.end_time.timestamp())}


def test_a_manager_has_the_organizers_room_and_every_room_of_their_sphere(
    sphere, active_user, now, window
):
    sphere.managers.add(active_user)
    ended = _event(sphere, now, ended_days_ago=3, name="Ended")
    readable = SessionFactory(
        event=ended, category=None, title="Readable", status=SessionStatus.ACCEPTED
    )
    banned = _event(sphere, now, name="Banned")
    SessionFactory(event=banned, category=None, title="Banned")
    EventBan.objects.create(event=banned, user=active_user)
    expired = _event(sphere, now, ended_days_ago=31, name="Expired")
    SessionFactory(event=expired, category=None, title="Expired")
    SessionFactory(event=_event(SphereFactory(), now), category=None, title="Foreign")

    access = ParleyRepository().read_access(user_id=active_user.pk, window=window)

    assert access is not None
    assert access.managed_sphere_ids == [sphere.pk]
    assert _rooms(access) == [
        (f"organizers:{sphere.pk}", True, True),
        (f"event:{sphere.pk}:{ended.pk}", False, True),
        (f"session:{sphere.pk}:{readable.pk}", False, True),
    ]
    assert access.rooms[0].title == sphere.name


def test_an_event_its_organizers_turned_chat_off_for_keeps_only_its_sessions(
    sphere, active_user, now, window
):
    event = _event(sphere, now, parley_enabled=False)
    session = SessionFactory(event=event, category=None, status=SessionStatus.ACCEPTED)
    SessionParticipationFactory(
        session=session, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )

    access = ParleyRepository().read_access(user_id=active_user.pk, window=window)

    assert access is not None
    assert [room.id for room in access.rooms] == [f"session:{sphere.pk}:{session.pk}"]


def test_a_sphere_with_chat_off_offers_no_room_at_all(sphere, active_user, now, window):
    sphere.parley_enabled = False
    sphere.save()
    sphere.managers.add(active_user)
    SessionParticipationFactory(
        session=SessionFactory(event=_event(sphere, now), category=None),
        user=active_user,
        status=SessionParticipationStatus.CONFIRMED,
    )
    repository = ParleyRepository()

    access = repository.read_access(user_id=active_user.pk, window=window)

    assert access is not None
    assert (access.rooms, access.managed_sphere_ids) == ([], [])
    assert repository.has_rooms(user_id=active_user.pk, window=window) is False


@pytest.mark.parametrize("taking_part", ("manager", "player", "nobody"))
def test_says_whether_someone_has_any_room(
    sphere, active_user, now, window, taking_part
):
    if taking_part == "manager":
        sphere.managers.add(active_user)
    elif taking_part == "player":
        SessionParticipationFactory(
            session=SessionFactory(event=_event(sphere, now), category=None),
            user=active_user,
            status=SessionParticipationStatus.WAITING,
        )

    has_rooms = ParleyRepository().has_rooms(user_id=active_user.pk, window=window)

    assert has_rooms is (taking_part != "nobody")


@pytest.mark.parametrize("attribute", ("is_active", "user_type"))
def test_denies_disabled_or_inactive_accounts(sphere, active_user, window, attribute):
    sphere.managers.add(active_user)
    if attribute == "is_active":
        active_user.is_active = False
    else:
        active_user.user_type = "connected"
    active_user.save()
    repository = ParleyRepository()

    assert repository.read_access(user_id=active_user.pk, window=window) is None
    assert repository.has_rooms(user_id=active_user.pk, window=window) is False
