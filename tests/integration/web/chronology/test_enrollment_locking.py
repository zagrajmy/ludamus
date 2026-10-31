from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from threading import Condition

import pytest
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import Client
from django.urls import reverse

from ludamus.links.db.django.enrollment import ParticipationPromotionRepository
from ludamus.links.db.django.models import (
    EnrollmentConfig,
    SessionParticipation,
    SessionParticipationStatus,
    UserEnrollmentConfig,
)
from ludamus.mills.enrollment import EnrollmentService
from ludamus.pacts.crowd import UserType
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
    sponsor_user,
)
from tests.integration.utils import assert_response
from tests.integration.web.chronology.helpers import enroll_context, participation_row

# Long enough that a request which is not blocked on a lock reaches the
# rendezvous in time; a request blocked on one never does, and the other then
# goes on alone after this many seconds.
_RENDEZVOUS_SECONDS = 2
_CONTENDERS = 2


class _Rendezvous:
    # Holds the first two arrivals until both are there, so each request has
    # read the state it decides on before either writes. A request that is
    # serialised behind a row lock never arrives; the first then goes on alone.
    def __init__(self) -> None:
        self._condition = Condition()
        self._arrived = 0
        self._open = True

    def __call__(self) -> None:
        with self._condition:
            if not self._open:
                return
            self._arrived += 1
            if self._arrived == _CONTENDERS:
                self._open = False
                self._condition.notify_all()
                return
            self._condition.wait_for(
                lambda: not self._open, timeout=_RENDEZVOUS_SECONDS
            )
            self._open = False


def _hold_writes(monkeypatch, rendezvous):
    # Every seat write on the enroll and promotion paths waits at the
    # rendezvous first, after its checks have run.
    save = SessionParticipation.save
    confirm = ParticipationPromotionRepository.confirm

    def held_save(self, *args, **kwargs):
        rendezvous()
        return save(self, *args, **kwargs)

    def held_confirm(participation_ids):
        rendezvous()
        return confirm(participation_ids)

    monkeypatch.setattr(SessionParticipation, "save", held_save)
    monkeypatch.setattr(
        ParticipationPromotionRepository, "confirm", staticmethod(held_confirm)
    )


def _scheduled(event, *, start, presenter, limit=10):
    session = SessionFactory(
        event=event,
        category=None,
        presenter=presenter,
        participants_limit=limit,
        min_age=0,
    )
    AgendaItemFactory(
        session=session,
        space=SpaceFactory(event=event),
        start_time=start,
        end_time=start + timedelta(hours=2),
    )
    return session


def _enroll_url(session):
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": session.event.slug, "session_id": session.pk},
    )


def _client_for(user):
    client = Client()
    client.force_login(user)
    return client


def _post_at_once(posts):
    def post(client, url, data):
        try:
            return client.post(url, data=data)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(posts)) as pool:
        futures = [pool.submit(post, *args) for args in posts]
        return [future.result() for future in futures]


def _status(user, session):
    return (
        SessionParticipation.objects.filter(user=user, session=session)
        .values_list("status", flat=True)
        .first()
    )


def _player(username):
    return UserFactory(
        username=username, email=f"{username}@example.com", password=make_password(None)
    )


def _restricted_window(event, *, owner, passes):
    now = datetime.now(UTC)
    window = EnrollmentConfig.objects.create(
        event=event,
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=5),
        percentage_slots=100,
        restrict_to_configured_users=True,
    )
    UserEnrollmentConfig.objects.create(
        enrollment_config=window, user_email=owner.email, allowed_slots=passes
    )


def _companions(owner, *names):
    companions = [
        UserFactory(
            username=name.lower(),
            name=name,
            email=f"{name.lower()}@example.com",
            user_type=UserType.CONNECTED,
            manager=owner,
        )
        for name in names
    ]
    for companion in companions:
        sponsor_user(leader=owner, member=companion)
    return companions


def _three_sessions(event):
    presenter = UserFactory(username="host", email="host@example.com")
    return [
        _scheduled(
            event, start=event.start_time + timedelta(hours=3 * n), presenter=presenter
        )
        for n in range(3)
    ]


def _allowance_spent(name):
    return (
        f"{name}: Cannot enroll more users. You have already enrolled 2 out of 2 "
        "unique people (each person can enroll in multiple sessions). Only 0 "
        "slots remaining for new people."
    )


@pytest.mark.usefixtures("enrollment_config")
class TestHeldSeatCountsAsAConflict:
    def test_an_offered_seat_blocks_enrolling_in_an_overlapping_session(
        self, client, event, active_user
    ):
        start = event.start_time + timedelta(hours=1)
        offered_in = _scheduled(event, start=start, presenter=active_user)
        overlapping = _scheduled(
            event, start=start + timedelta(hours=1), presenter=active_user
        )
        player = _player("player")
        SessionParticipation.objects.create(
            session=offered_in,
            user=player,
            status=SessionParticipationStatus.OFFERED,
            claim_token="held-for-player",
            offer_expires_at=datetime.now(UTC) + timedelta(hours=2),
        )
        client.force_login(player)

        response = client.post(
            _enroll_url(overlapping), data={f"user_{player.pk}": "enroll"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. enroll is not one of the available "
                        "choices."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data=enroll_context(
                session=overlapping,
                user_data=[participation_row(player, has_time_conflict=True)],
            ),
            template_name="chronology/enroll_select.html",
        )
        assert _status(player, overlapping) is None


class TestAllowanceIsRecheckedUnderTheLock:
    def test_a_seat_taken_after_the_form_check_refuses_a_third_person(
        self, monkeypatch, client, event, active_user
    ):
        _restricted_window(event, owner=active_user, passes=2)
        seated_in, elsewhere, target = _three_sessions(event)
        first, second = _companions(active_user, "First", "Second")
        SessionParticipation.objects.create(
            session=seated_in,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        can_enroll_users = EnrollmentService.can_enroll_users
        answers = []

        def first_seated_meanwhile(self, **kwargs):
            allowed = can_enroll_users(self, **kwargs)
            if not answers:
                # Another request seats First and commits between this
                # request's form check and its lock.
                SessionParticipation.objects.create(
                    session=elsewhere,
                    user=first,
                    status=SessionParticipationStatus.CONFIRMED,
                )
            answers.append(allowed)
            return allowed

        monkeypatch.setattr(
            EnrollmentService, "can_enroll_users", first_seated_meanwhile
        )
        client.force_login(active_user)

        response = client.post(
            _enroll_url(target), data={f"user_{second.pk}": "enroll"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, _allowance_spent(second.name))],
            url=_enroll_url(target),
        )
        assert answers == [True, False]
        assert _status(second, target) is None


@pytest.mark.postgres
@pytest.mark.usefixtures("transactional_db", "enrollment_config")
class TestSeatDecisionsSerialisePerPerson:
    def test_two_enrolls_into_overlapping_sessions_seat_once(
        self, monkeypatch, event, active_user
    ):
        start = event.start_time + timedelta(hours=1)
        first = _scheduled(event, start=start, presenter=active_user)
        second = _scheduled(
            event, start=start + timedelta(hours=1), presenter=active_user
        )
        player = _player("player")
        _hold_writes(monkeypatch, _Rendezvous())

        responses = _post_at_once(
            [
                (
                    _client_for(player),
                    _enroll_url(session),
                    {f"user_{player.pk}": "enroll"},
                )
                for session in (first, second)
            ]
        )

        statuses = [_status(player, first), _status(player, second)]
        assert sorted(statuses, key=str) == [
            None,
            SessionParticipationStatus.CONFIRMED.value,
        ]
        won = statuses.index(SessionParticipationStatus.CONFIRMED.value)
        url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        assert_response(
            responses[won],
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {player.name}")],
            url=url,
        )
        assert_response(
            responses[1 - won],
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.WARNING,
                    (
                        "Skipped (already enrolled or conflicts): "
                        f"{player.name} (time conflict)"
                    ),
                )
            ],
            url=url,
        )

    def test_promotion_and_enroll_never_seat_a_waiter_twice(
        self, monkeypatch, event, active_user
    ):
        start = event.start_time + timedelta(hours=1)
        full = _scheduled(event, start=start, presenter=active_user, limit=1)
        overlapping = _scheduled(
            event, start=start + timedelta(hours=1), presenter=active_user
        )
        leaver = _player("leaver")
        player = _player("player")
        SessionParticipation.objects.create(
            session=full, user=leaver, status=SessionParticipationStatus.CONFIRMED
        )
        SessionParticipation.objects.create(
            session=full, user=player, status=SessionParticipationStatus.WAITING
        )
        _hold_writes(monkeypatch, _Rendezvous())

        responses = _post_at_once(
            [
                (
                    _client_for(leaver),
                    _enroll_url(full),
                    {f"user_{leaver.pk}": "cancel"},
                ),
                (
                    _client_for(player),
                    _enroll_url(overlapping),
                    {f"user_{player.pk}": "enroll"},
                ),
            ]
        )

        # The enroll may also be refused by its form, if the promotion
        # committed before the form was built.
        assert responses[0].status_code == HTTPStatus.FOUND
        assert responses[1].status_code in {HTTPStatus.OK, HTTPStatus.FOUND}
        assert _status(leaver, full) is None
        assert (_status(player, full), _status(player, overlapping)) in {
            (SessionParticipationStatus.CONFIRMED.value, None),
            (
                SessionParticipationStatus.WAITING.value,
                SessionParticipationStatus.CONFIRMED.value,
            ),
        }


@pytest.mark.postgres
@pytest.mark.usefixtures("transactional_db")
class TestSeatDecisionsSerialisePerPassOwner:
    def test_two_companions_into_two_sessions_never_overspend(
        self, monkeypatch, event, active_user
    ):
        _restricted_window(event, owner=active_user, passes=2)
        seated_in, *targets = _three_sessions(event)
        companions = _companions(active_user, "First", "Second")
        SessionParticipation.objects.create(
            session=seated_in,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        _hold_writes(monkeypatch, _Rendezvous())

        responses = _post_at_once(
            [
                (
                    _client_for(active_user),
                    _enroll_url(session),
                    {f"user_{companion.pk}": "enroll"},
                )
                for session, companion in zip(targets, companions, strict=True)
            ]
        )

        seated = [
            _status(companion, session)
            for session, companion in zip(targets, companions, strict=True)
        ]
        assert sorted(seated, key=str) == [
            None,
            SessionParticipationStatus.CONFIRMED.value,
        ]
        refused = seated.index(None)
        assert_response(
            responses[refused],
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, _allowance_spent(companions[refused].name))],
            url=_enroll_url(targets[refused]),
        )
