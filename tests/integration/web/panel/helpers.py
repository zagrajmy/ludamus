"""Shared arrange/assert helpers for panel integration tests."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import ProposalCategory, Session
from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import TimetableGridDTO
from ludamus.specs.timetable import TIMETABLE_SLOT_MINUTES, TIMETABLE_SNAP_MINUTES
from tests.integration.conftest import SessionFactory
from tests.integration.utils import assert_response

if TYPE_CHECKING:
    from django.http import HttpResponse

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
EVENT_NOT_FOUND_ERROR = "Event not found."
PROPOSAL_NOT_FOUND_ERROR = "Proposal not found."
SCHEDULED_ERROR = (
    "This session is scheduled and can only be accepted. "
    "Remove it from the timetable to change its status."
)

EMPTY_STATS = {
    "hosts_count": 0,
    "pending_proposals": 0,
    "rooms_count": 0,
    "scheduled_sessions": 0,
    "total_proposals": 0,
    "total_sessions": 0,
}


def panel_context(event, *, active_nav: str | None = None, **stats: int) -> dict:
    # Every panel page renders the sidebar from these keys. Pass stats that
    # differ from empty as keyword arguments: panel_context(event, rooms_count=2)
    context = {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": EMPTY_STATS | stats,
    }
    if active_nav:
        context["active_nav"] = active_nav
    return context


def assert_login_required(response: HttpResponse, url: str) -> None:
    assert_response(
        response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
    )


def assert_not_a_manager(response: HttpResponse) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, PERMISSION_ERROR)],
        url="/",
    )


def assert_event_not_found(response: HttpResponse) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, EVENT_NOT_FOUND_ERROR)],
        url="/panel/",
    )


def assert_proposal_not_found(response: HttpResponse, event) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, PROPOSAL_NOT_FOUND_ERROR)],
        url=reverse("panel:proposals", kwargs={"slug": event.slug}),
    )


def assert_scheduled_proposal_refused(response: HttpResponse, event, session) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, SCHEDULED_ERROR)],
        url=reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        ),
    )


def make_timetable_session(category, *, status="pending", participants_limit=5):
    return SessionFactory(
        category=category,
        status=status,
        participants_limit=participants_limit,
        min_age=0,
    )


def assign_payload(session, space, start, end):
    return {
        "session_pk": session.pk,
        "space_pk": space.pk,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }


def empty_grid():
    return TimetableGridDTO(
        spaces=[],
        groups=[],
        days=[],
        time_labels=[],
        total_minutes=0,
        slot_minutes=TIMETABLE_SLOT_MINUTES,
        snap_minutes=TIMETABLE_SNAP_MINUTES,
        page=1,
        total_pages=1,
        total_spaces=0,
        total_columns=0,
        available_dates=[],
    )


def cfp_tab_urls(event):
    return {
        "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
        "host": reverse("panel:personal-data-fields", kwargs={"slug": event.slug}),
        "session": reverse("panel:session-fields", kwargs={"slug": event.slug}),
        "time_slots": reverse("panel:time-slots", kwargs={"slug": event.slug}),
    }


def assert_facilitator_not_found(response: HttpResponse, event) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, "Facilitator not found.")],
        url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
    )


def make_proposal(event, **kwargs):
    # The pending RPG proposal the panel action tests all start from.
    category, _ = ProposalCategory.objects.get_or_create(
        event=event, slug="rpg", defaults={"name": "RPG"}
    )
    return Session.objects.create(
        **{
            "event": event,
            "category": category,
            "presenter": None,
            "display_name": "Test Host",
            "title": "Test Session",
            "slug": "test-session",
            "participants_limit": 5,
            "status": "pending",
            **kwargs,
        }
    )
