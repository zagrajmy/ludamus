"""Shared assert helpers for multiverse (sphere panel) integration tests."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.contrib import messages

from tests.integration.utils import assert_response

if TYPE_CHECKING:
    from django.http import HttpResponse

PERMISSION_ERROR = "You don't have permission to access the sphere panel."

TAB_URLS = {
    "general": "/multiverse/panel/",
    "announcements": "/multiverse/panel/announcements/",
    "connections": "/multiverse/panel/connections/",
}


def sphere_sidebar_context(*, active_nav: str) -> dict:
    return {
        "events": [],
        "current_event": None,
        "is_proposal_active": False,
        "active_nav": active_nav,
    }


def sphere_settings_context(*, active_tab: str) -> dict:
    return sphere_sidebar_context(active_nav="sphere-settings") | {
        "active_tab": active_tab,
        "tab_urls": TAB_URLS,
    }


def assert_not_a_sphere_manager(response: HttpResponse) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, PERMISSION_ERROR)],
        url="/",
    )
