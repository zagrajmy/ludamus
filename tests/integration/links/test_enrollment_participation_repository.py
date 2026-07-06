from ludamus.adapters.db.django.models import (
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.links.db.django.enrollment import EnrollmentParticipationRepository
from ludamus.pacts.enrollment import GuestSeatData
from tests.integration.conftest import SessionFactory, UserFactory


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
