from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.enrollment import EnrollmentParticipationRepository
from ludamus.links.db.django.models import (
    Session,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts.enrollment import GuestSeatData
from tests.integration.conftest import AgendaItemFactory, SessionFactory, UserFactory

_TEN = datetime(2026, 6, 1, 10, tzinfo=UTC)


class TestOccupyingUserIds:
    def test_counts_confirmed_and_offered_distinct_per_event(self, event):
        session_a = SessionFactory(event=event, category=None)
        session_b = SessionFactory(event=event, category=None)
        occupier = UserFactory(username="occupier", email="occupier@example.com")
        offered = UserFactory(username="offered", email="offered@example.com")
        # Same user holding a seat in two sessions of the event is one distinct id.
        SessionParticipation.objects.create(
            session=session_a,
            user=occupier,
            status=SessionParticipationStatus.CONFIRMED.value,
        )
        SessionParticipation.objects.create(
            session=session_b,
            user=occupier,
            status=SessionParticipationStatus.CONFIRMED.value,
        )
        SessionParticipation.objects.create(
            session=session_a,
            user=offered,
            status=SessionParticipationStatus.OFFERED.value,
        )

        result = EnrollmentParticipationRepository.occupying_user_ids(
            user_ids=[occupier.pk, offered.pk], event_id=event.pk
        )

        assert result == {occupier.pk, offered.pk}

    def test_excludes_waiting_status(self, event):
        session = SessionFactory(event=event, category=None)
        waiter = UserFactory(username="waiter", email="waiter@example.com")
        SessionParticipation.objects.create(
            session=session,
            user=waiter,
            status=SessionParticipationStatus.WAITING.value,
        )

        result = EnrollmentParticipationRepository.occupying_user_ids(
            user_ids=[waiter.pk], event_id=event.pk
        )

        assert result == set()

    def test_filters_by_event(self, event):
        session = SessionFactory(event=event, category=None)
        other_session = SessionFactory(category=None)
        user = UserFactory(username="enrolled", email="enrolled@example.com")
        SessionParticipation.objects.create(
            session=other_session,
            user=user,
            status=SessionParticipationStatus.CONFIRMED.value,
        )
        SessionParticipation.objects.create(
            session=session,
            user=user,
            status=SessionParticipationStatus.CONFIRMED.value,
        )

        result = EnrollmentParticipationRepository.occupying_user_ids(
            user_ids=[user.pk], event_id=other_session.event.pk
        )

        assert result == {user.pk}

    def test_filters_by_user_set(self, event):
        session = SessionFactory(event=event, category=None)
        wanted = UserFactory(username="wanted", email="wanted@example.com")
        unwanted = UserFactory(username="unwanted", email="unwanted@example.com")
        for user in (wanted, unwanted):
            SessionParticipation.objects.create(
                session=session,
                user=user,
                status=SessionParticipationStatus.CONFIRMED.value,
            )

        result = EnrollmentParticipationRepository.occupying_user_ids(
            user_ids=[wanted.pk], event_id=event.pk
        )

        assert result == {wanted.pk}


class TestCreateConfirmed:
    def test_persists_confirmed_participation(self, event, active_user):
        session = SessionFactory(event=event, category=None)
        guest = UserFactory(username="guest", email="guest@example.com")
        seat = GuestSeatData(
            session_id=session.pk,
            user_id=guest.pk,
            party_id=None,
            enrolled_by_id=active_user.pk,
        )

        EnrollmentParticipationRepository.create_confirmed(seat)

        participation = SessionParticipation.objects.get(session=session, user=guest)
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert participation.party_id is None
        assert participation.enrolled_by_id == active_user.pk


class TestConflictedUserIds:
    @staticmethod
    def _scheduled(event, *, start_hour: float, end_hour: float):
        return AgendaItemFactory(
            session=SessionFactory(event=event, category=None),
            start_time=_TEN + timedelta(hours=start_hour - 10),
            end_time=_TEN + timedelta(hours=end_hour - 10),
        ).session

    @pytest.mark.parametrize(
        ("start_hour", "end_hour", "conflicts"),
        (
            pytest.param(9, 13, True, id="contains-the-candidate"),
            pytest.param(10.5, 11.5, True, id="inside-the-candidate"),
            pytest.param(9, 11, True, id="ends-inside"),
            pytest.param(11, 13, True, id="starts-inside"),
            pytest.param(10, 12, True, id="same-window"),
            pytest.param(8, 10, False, id="ends-as-candidate-starts"),
            pytest.param(12, 14, False, id="starts-as-candidate-ends"),
        ),
    )
    def test_a_confirmed_seat_conflicts_exactly_when_the_windows_overlap(
        self, event, *, start_hour: float, end_hour: float, conflicts: bool
    ):
        candidate = self._scheduled(event, start_hour=10, end_hour=12)
        other = self._scheduled(event, start_hour=start_hour, end_hour=end_hour)
        user = UserFactory()
        SessionParticipation.objects.create(
            session=other, user=user, status=SessionParticipationStatus.CONFIRMED
        )

        result = Session.objects.conflicted_user_ids(candidate, [user.pk])

        assert result == ({user.pk} if conflicts else set())

    def test_only_confirmed_seats_of_the_asked_users_conflict(self, event):
        candidate = self._scheduled(event, start_hour=10, end_hour=12)
        containing = self._scheduled(event, start_hour=9, end_hour=13)
        seated, waiting, unasked = UserFactory(), UserFactory(), UserFactory()
        for user, status in (
            (seated, SessionParticipationStatus.CONFIRMED),
            (waiting, SessionParticipationStatus.WAITING),
            (unasked, SessionParticipationStatus.CONFIRMED),
        ):
            SessionParticipation.objects.create(
                session=containing, user=user, status=status
            )

        result = Session.objects.conflicted_user_ids(candidate, [seated.pk, waiting.pk])

        assert result == {seated.pk}
