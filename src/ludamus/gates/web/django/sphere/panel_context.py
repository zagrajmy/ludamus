# Sidebar and tab context shared by every sphere-panel page. The pages
# themselves still live under `multiverse/` and are reached as
# `multiverse:panel:*`; this helper moved ahead of them because the guild pages
# in this package need it too, and it is sphere infrastructure, not
# multiverse-specific.
from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.urls import reverse

from ludamus.mills.event import is_proposal_active

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.gates.web.django.multiverse.access import MultiverseRequest
    from ludamus.pacts import EventDTO


class SphereSidebar(TypedDict):
    events: Sequence[EventDTO]
    current_event: EventDTO | None
    is_proposal_active: bool
    active_nav: str


class SphereSettings(SphereSidebar):
    active_tab: str
    tab_urls: dict[str, str]


def sphere_sidebar_context(
    request: MultiverseRequest, *, active_nav: str
) -> SphereSidebar:
    """Build context for a sphere page that is its own sidebar entry.

    Guilds is one. `current_event` defaults to the most recent sphere event so
    the event panel sidebar (rendered from `panel/base.html`) has something to
    link to. When the sphere has no events the sidebar gracefully hides
    event-scoped items.

    Returns:
        The sidebar keys, with `active_nav` naming the entry to highlight.
    """
    events = request.services.sphere_panel.list_events(
        request.context.current_sphere_id
    )
    current_event = events[0] if events else None

    return {
        "events": events,
        "current_event": current_event,
        "is_proposal_active": (
            is_proposal_active(current_event) if current_event else False
        ),
        "active_nav": active_nav,
    }


def sphere_settings_context(
    request: MultiverseRequest, *, active_tab: str
) -> SphereSettings:
    """Build context for a page inside Sphere settings.

    Named apart from `sphere_sidebar_context` because passing the wrong one
    fails silently: a tab strip rendered without `active_tab` selects nothing
    rather than raising.

    Tab hrefs are reversed here rather than in the template. `{% url … as … %}`
    swallows NoReverseMatch and yields `href=""`, so a renamed route would point
    the whole strip at the current page without a word; `reverse` raises. This
    also keeps the strip shaped like the eight other `*_tab_urls` producers.

    Returns:
        The sidebar keys plus the tab strip's `active_tab` and hrefs.
    """
    return {
        **sphere_sidebar_context(request, active_nav="sphere-settings"),
        "active_tab": active_tab,
        "tab_urls": {
            "general": reverse("multiverse:panel:sphere-settings"),
            "announcements": reverse("multiverse:panel:announcements"),
            "connections": reverse("multiverse:panel:connections"),
            "mcp": reverse("multiverse:panel:mcp-token"),
        },
    }
