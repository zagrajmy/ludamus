import logging

import pytest

from ludamus.inits.services import Services
from ludamus.links.db.django.models import (
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
    def test_session_outside_every_window_says_so(self, session, caplog):
        with caplog.at_level(logging.INFO):
            result = _service().fill_freed_seats(session_id=session.pk)

        assert not result.promoted
        assert "outside every active enrollment window" in caplog.text

    @pytest.mark.usefixtures("enrollment_config", "agenda_item")
    def test_full_session_reports_seats_and_waiters(self, session, waiter, caplog):
        session.participants_limit = 1
        session.save()
        SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.CONFIRMED
        )

        with caplog.at_level(logging.INFO):
            _service().fill_freed_seats(session_id=session.pk)

        assert "0 seats free, 0 waiting" in caplog.text
