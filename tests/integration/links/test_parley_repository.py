from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.models import EventBan, Facilitator, SphereMembership
from ludamus.links.db.django.parley import ParleyRepository
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.parley import ParleyTeamSeat, ParleyTimeWindow
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.sphere import SphereRole
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


def _event(sphere, now, *, ended_days_ago=-1, parley_enabled=True, **fields):
    end = now - timedelta(days=ended_days_ago)
    return EventFactory(
        sphere=sphere,
        publication_time=end - timedelta(days=3),
        start_time=end - timedelta(hours=10),
        end_time=end,
        parley_enabled=parley_enabled,
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

    access = ParleyRepository().read_access(
        user_id=active_user.pk, window=window, moderated=frozenset()
    )

    assert access is not None
    assert sorted(_rooms(access)) == sorted(
        [
            (f"event:{sphere.pk}:{event.pk}", True, False),
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

    access = ParleyRepository().read_access(
        user_id=active_user.pk, window=window, moderated=frozenset({sphere.pk})
    )

    assert access is not None
    assert _rooms(access) == [
        (f"organizers:{sphere.pk}", True, True),
        (f"event:{sphere.pk}:{ended.pk}", False, True),
        (f"session:{sphere.pk}:{readable.pk}", False, True),
    ]
    assert access.rooms[0].title == sphere.name


def test_a_manager_s_own_rooms_stand_apart_from_the_ones_they_only_moderate(
    sphere, active_user, now, window
):
    sphere.managers.add(active_user)
    event = _event(sphere, now, name="Bachanalia")
    played = SessionFactory(
        event=event, category=None, title="Played", status=SessionStatus.ACCEPTED
    )
    SessionParticipationFactory(
        session=played, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )
    watched = SessionFactory(
        event=event, category=None, title="Watched", status=SessionStatus.ACCEPTED
    )
    unvisited = _event(sphere, now, name="Polcon")
    elsewhere = _event(SphereFactory(), now, name="Elsewhere")
    joined = SessionFactory(
        event=elsewhere, category=None, title="Joined", status=SessionStatus.ACCEPTED
    )
    SessionParticipationFactory(
        session=joined, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )

    access = ParleyRepository().read_access(
        user_id=active_user.pk, window=window, moderated=frozenset({sphere.pk})
    )

    assert access is not None
    assert sorted(
        (room.id, room.moderating, room.event_title) for room in access.rooms
    ) == sorted(
        [
            (f"organizers:{sphere.pk}", False, None),
            (f"event:{sphere.pk}:{event.pk}", False, None),
            (f"event:{sphere.pk}:{unvisited.pk}", True, None),
            (f"event:{elsewhere.sphere_id}:{elsewhere.pk}", False, None),
            (f"session:{sphere.pk}:{played.pk}", False, "Bachanalia"),
            (f"session:{sphere.pk}:{watched.pk}", True, "Bachanalia"),
            (f"session:{elsewhere.sphere_id}:{joined.pk}", False, "Elsewhere"),
        ]
    )


@pytest.mark.parametrize(
    ("sphere_events", "own", "has_chat"),
    (
        (False, None, False),
        (True, None, True),
        (False, True, True),
        (True, False, False),
    ),
    ids=["follows-a-sphere-without", "inherits", "overrides-on", "overrides-off"],
)
def test_an_event_s_chat_follows_its_sphere_unless_it_says_otherwise(
    sphere, active_user, now, window, sphere_events, own, has_chat
):
    sphere.parley_events_enabled = sphere_events
    sphere.save()
    event = _event(sphere, now, parley_enabled=own)
    session = SessionFactory(event=event, category=None, status=SessionStatus.ACCEPTED)
    SessionParticipationFactory(
        session=session, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )

    access = ParleyRepository().read_access(
        user_id=active_user.pk, window=window, moderated=frozenset()
    )

    assert access is not None
    session_room = f"session:{sphere.pk}:{session.pk}"
    event_room = f"event:{sphere.pk}:{event.pk}"
    assert [room.id for room in access.rooms] == (
        [event_room, session_room] if has_chat else [session_room]
    )


def test_a_sphere_that_closes_its_organizers_room_keeps_its_other_rooms(
    sphere, active_user, now, window
):
    sphere.parley_organizers_enabled = False
    sphere.save()
    sphere.managers.add(active_user)
    session = SessionFactory(event=_event(sphere, now), category=None)
    repository = ParleyRepository()

    access = repository.read_access(
        user_id=active_user.pk, window=window, moderated=frozenset({sphere.pk})
    )

    assert access is not None
    assert [room.kind for room in access.rooms] == ["event", "session"]
    assert access.rooms[1].id == f"session:{sphere.pk}:{session.pk}"
    assert (
        repository.has_rooms(
            user_id=active_user.pk, window=window, moderated=frozenset({sphere.pk})
        )
        is True
    )


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

    access = repository.read_access(
        user_id=active_user.pk, window=window, moderated=frozenset()
    )

    assert access is not None
    assert access.rooms == []
    assert (
        repository.has_rooms(
            user_id=active_user.pk, window=window, moderated=frozenset()
        )
        is False
    )


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

    has_rooms = ParleyRepository().has_rooms(
        user_id=active_user.pk,
        window=window,
        moderated=frozenset({sphere.pk} if taking_part == "manager" else ()),
    )

    assert has_rooms is (taking_part != "nobody")


def test_lists_the_teams_of_spheres_with_chat_someone_is_on(sphere, active_user):
    sphere.managers.add(active_user)
    press = SphereFactory()
    SphereMembership.objects.create(
        sphere=press, user=active_user, role=SphereRole.COMMS
    )
    quiet = SphereFactory(parley_enabled=False)
    quiet.managers.add(active_user)

    seats = ParleyRepository().list_team_seats(active_user.pk)

    assert seats == [
        ParleyTeamSeat(sphere_id=sphere.pk, role=SphereRole.MANAGER),
        ParleyTeamSeat(sphere_id=press.pk, role=SphereRole.COMMS),
    ]


def test_hosting_a_programme_point_not_yet_accepted_leaves_the_event_s_chat_shut(
    sphere, active_user, now, window
):
    event = _event(sphere, now)
    pending = SessionFactory(event=event, category=None, status=SessionStatus.PENDING)
    pending.facilitators.add(
        Facilitator.objects.create(
            event=event, user=active_user, display_name=active_user.name, slug="ada"
        )
    )

    access = ParleyRepository().read_access(
        user_id=active_user.pk, window=window, moderated=frozenset()
    )

    assert access is not None
    assert [room.kind for room in access.rooms] == ["session"]


@pytest.mark.parametrize("attribute", ("is_active", "user_type"))
def test_denies_disabled_or_inactive_accounts(sphere, active_user, window, attribute):
    sphere.managers.add(active_user)
    if attribute == "is_active":
        active_user.is_active = False
    else:
        active_user.user_type = "connected"
    active_user.save()
    repository = ParleyRepository()

    assert (
        repository.read_access(
            user_id=active_user.pk, window=window, moderated=frozenset({sphere.pk})
        )
        is None
    )
    assert (
        repository.has_rooms(
            user_id=active_user.pk, window=window, moderated=frozenset({sphere.pk})
        )
        is False
    )
