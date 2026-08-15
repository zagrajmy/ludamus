import logging
from datetime import UTC, datetime, timedelta

import pytest

from ludamus.inits.services import Services
from ludamus.links.db.django.models import (
    DomainEnrollmentConfig,
    EnrollmentConfig,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts.legacy import PromotionMode
from tests.integration.conftest import ProposalCategoryFactory


def _service():
    return Services().waitlist_promotion


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestPresenterlessSession:
    def test_offer_reaches_a_waiter(
        self, session, event, waiter, django_capture_on_commit_callbacks
    ):
        session.participants_limit = 2
        session.presenter = None
        session.category = ProposalCategoryFactory(
            event=event, promotion_mode=PromotionMode.OFFER_CLAIM.value
        )
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        with django_capture_on_commit_callbacks(execute=True):
            result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert result.offered == [participation.pk]
        assert participation.status == SessionParticipationStatus.OFFERED.value


class TestSilentSkipsAreLogged:
    def test_unscheduled_session_says_so(self, session, caplog):
        with caplog.at_level(logging.INFO):
            result = _service().fill_freed_seats(session_id=session.pk)

        assert not result.offered
        assert "not on the timetable yet" in caplog.text

    @pytest.mark.usefixtures("agenda_item")
    def test_full_session_reports_seats_and_waiters(self, session, waiter, caplog):
        session.participants_limit = 1
        session.save()
        SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.CONFIRMED
        )

        with caplog.at_level(logging.INFO):
            _service().fill_freed_seats(session_id=session.pk)

        assert "0 seats free, 0 waiting" in caplog.text


@pytest.mark.usefixtures("agenda_item")
class TestPromotionAfterEnrollmentCloses:
    def test_promotes_with_no_enrollment_window(self, session, waiter):
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert result.promoted == [participation.pk]
        assert participation.status == SessionParticipationStatus.CONFIRMED.value

    def test_promotes_after_window_ends(self, session, event, waiter):
        now = datetime.now(UTC)
        EnrollmentConfig.objects.create(
            event=event,
            start_time=now - timedelta(days=10),
            end_time=now - timedelta(days=1),
            percentage_slots=100,
        )
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert result.promoted == [participation.pk]
        assert participation.status == SessionParticipationStatus.CONFIRMED.value

    def test_closed_window_still_respects_ticket_allowance(
        self, session, event, waiter
    ):
        now = datetime.now(UTC)
        closed = EnrollmentConfig.objects.create(
            event=event,
            start_time=now - timedelta(days=10),
            end_time=now - timedelta(days=1),
            percentage_slots=100,
        )
        DomainEnrollmentConfig.objects.create(
            enrollment_config=closed,
            domain=waiter.email.split("@")[1],
            allowed_slots_per_user=0,
        )
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert not result.promoted
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.WAITING.value

    def test_later_closed_window_rules_override_earlier_ones(
        self, session, event, waiter
    ):
        now = datetime.now(UTC)
        early = EnrollmentConfig.objects.create(
            event=event,
            start_time=now - timedelta(days=20),
            end_time=now - timedelta(days=10),
            percentage_slots=100,
        )
        DomainEnrollmentConfig.objects.create(
            enrollment_config=early,
            domain=waiter.email.split("@")[1],
            allowed_slots_per_user=0,
        )
        EnrollmentConfig.objects.create(
            event=event,
            start_time=now - timedelta(days=9),
            end_time=now - timedelta(days=1),
            percentage_slots=100,
        )
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert result.promoted == [participation.pk]
        assert participation.status == SessionParticipationStatus.CONFIRMED.value

    def test_unlimited_session_promotes_after_close(self, session, waiter):
        session.participants_limit = 0
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert result.promoted == [participation.pk]
        assert participation.status == SessionParticipationStatus.CONFIRMED.value

    def test_future_only_windows_do_not_block_promotion(self, session, event, waiter):
        now = datetime.now(UTC)
        EnrollmentConfig.objects.create(
            event=event,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=5),
            percentage_slots=100,
        )
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert result.promoted == [participation.pk]
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert event.get_allowance_enrollment_configs() == []
