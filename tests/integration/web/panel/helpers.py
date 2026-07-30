"""Shared arrange/assert helpers for panel integration tests."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.contrib import messages

from ludamus.pacts import EventDTO
from tests.integration.utils import assert_response

if TYPE_CHECKING:
    from django.http import HttpResponse

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
EVENT_NOT_FOUND_ERROR = "Event not found."

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
