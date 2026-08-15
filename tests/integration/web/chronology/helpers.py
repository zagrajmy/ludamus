"""Shared arrange helpers for chronology integration tests."""

from unittest.mock import ANY

from ludamus.gates.web.django.chronology.enrollment_presentation import (
    SessionUserParticipationData,
)
from ludamus.inits.services import Services
from ludamus.links.db.django.models import SessionParticipation
from ludamus.pacts import SessionParticipationStatus
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)


def schedule_context(url: str) -> dict[str, object]:
    # The compact-schedule context keys shared by every card-layout response;
    # splatted into the exact-equality context assertions so adding a key is a
    # one-line change instead of a 36-site sweep.
    return {
        "compact_schedule": False,
        "schedule_days": [],
        "schedule_view_is_list": True,
        "schedule_view_is_rooms": False,
        "room_lane_days": [],
        "schedule_list_url": url,
        "schedule_rooms_url": f"{url}?view=rooms",
    }


def party_context(viewer):
    # The enroll page's party plumbing, derived from the same service call the
    # view makes (default selection: no explicit party requested).
    selection = Services().parties.enrollment_selection(
        viewer_pk=viewer.pk, requested_party=None
    )
    return {"party_choices": selection.choices, "selected_party": selection.selected}


def enroll_page_context(*, viewer, agenda_item, **overrides):
    # The enroll page as it renders for a viewer with no companions and no
    # participation yet.
    return {
        **party_context(viewer),
        "companions": [],
        "event": agenda_item.space.event,
        "form": ANY,
        "session": agenda_item.session,
        "shadowban_warnings": [],
        "user_data": [
            SessionUserParticipationData(
                user=UserDTO.model_validate(viewer),
                user_enrolled=False,
                user_waiting=False,
                has_time_conflict=False,
            )
        ],
        **overrides,
    }


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
