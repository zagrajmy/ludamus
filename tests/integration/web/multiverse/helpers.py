"""Shared assert helpers for multiverse (sphere panel) integration tests."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.contrib import messages

from tests.integration.utils import assert_response

if TYPE_CHECKING:
    from django.http import HttpResponse

PERMISSION_ERROR = "You don't have permission to access the sphere panel."


# Mirrors gates.web.django.sphere.panel_context. Kept deliberately small: tab
# hrefs are reversed in the template now, so there is no URL table to keep in
# step here.
def sphere_sidebar_context(*, active_nav: str) -> dict:
    return {
        "events": [],
        "current_event": None,
        "is_proposal_active": False,
        "active_nav": active_nav,
    }


def sphere_settings_context(*, active_tab: str) -> dict:
    return sphere_sidebar_context(active_nav="sphere-settings") | {
        "active_tab": active_tab
    }


def assert_not_a_sphere_manager(response: HttpResponse) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, PERMISSION_ERROR)],
        url="/",
    )
