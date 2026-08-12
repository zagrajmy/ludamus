# Sidebar and tab context shared by every sphere-panel page. The pages
# themselves still live under `multiverse/` and are reached as
# `multiverse:panel:*`; this helper moved ahead of them because the guild pages
# in this package need it too, and it is sphere infrastructure, not
# multiverse-specific.
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from django.urls import reverse

from ludamus.gates.web.django.panel import PanelNavContext
from ludamus.mills.event import is_proposal_active

# The four tabs in _sphere_tabs_nav.html. Closed for the same reason as the
# nav keys: a strip whose `active_tab` matches no tab selects nothing, and a
# `tab_urls` key the template does not ask for resolves to "" — pointing the
# tab at the current page. Reversing in Python catches a renamed *route*;
# this catches a renamed *key*.
SphereTab = Literal["general", "announcements", "connections", "mcp"]

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.gates.web.django.multiverse.access import MultiverseRequest
    from ludamus.gates.web.django.panel import PanelNav
    from ludamus.pacts import EventDTO


class SphereSidebar(PanelNavContext):
    events: Sequence[EventDTO]
    current_event: EventDTO | None
    is_proposal_active: bool


class SphereSettings(SphereSidebar):
    active_tab: SphereTab
    tab_urls: dict[SphereTab, str]


# `current_event` defaults to the most recent sphere event so the event panel
# sidebar (rendered from `panel/base.html`) has something to link to. A sphere
# with no events gracefully hides the event-scoped items.
def sphere_sidebar_context(
    request: MultiverseRequest, *, active_nav: PanelNav
) -> SphereSidebar:
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


# Named apart from `sphere_sidebar_context` because passing the wrong one fails
# silently: a tab strip rendered without `active_tab` selects nothing rather
# than raising. Hrefs are reversed here for the same reason `{% sidebar_link %}`
# reverses in Python — `{% url … as … %}` would swallow a renamed route and
# point the whole strip at the current page.
def sphere_settings_context(
    request: MultiverseRequest, *, active_tab: SphereTab
) -> SphereSettings:
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
