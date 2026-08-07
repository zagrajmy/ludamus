"""Shared arrange helpers for chronology integration tests."""

from ludamus.links.db.django.models import SessionParticipation
from ludamus.pacts import SessionParticipationStatus
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)


def make_half_full_session(event, *, participants_limit=2):
    # A scheduled session with one confirmed and one offered seat, so the
    # offered seat is what pushes it to full.
    space = SpaceFactory(event=event)
    session = SessionFactory(
        event=event, category=None, participants_limit=participants_limit
    )
    AgendaItemFactory(session=session, space=space)
    for status in (
        SessionParticipationStatus.CONFIRMED,
        SessionParticipationStatus.OFFERED,
    ):
        SessionParticipation.objects.create(
            session=session, user=UserFactory(), status=status
        )
    return session
