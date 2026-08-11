# Sidebar and tab context shared by every sphere-panel page. The pages
# themselves still live under `multiverse/` and are reached as
# `multiverse:panel:*`; this helper moved ahead of them because the guild pages
# in this package need it too, and it is sphere infrastructure, not
# multiverse-specific.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.urls import reverse

from ludamus.mills.event import is_proposal_active

if TYPE_CHECKING:
    from ludamus.gates.web.django.multiverse.access import MultiverseRequest

# One alias rather than repeating `dict[str, Any]` per builder: a template
# context is untyped by nature, and naming it keeps the `Any` to a single use.
type PanelContext = dict[str, Any]


def sphere_panel_nav(request: MultiverseRequest, *, active_nav: str) -> PanelContext:
    """Build sidebar-only context for a sphere-scoped panel page.

    For sphere pages that are their own sidebar entry rather than a tab inside
    Sphere settings — Guilds is one. `current_event` defaults to the most
    recent sphere event so the event panel sidebar (rendered from
    `panel/base.html`) has something to link to. When the sphere has no events
    the sidebar gracefully hides event-scoped items.

    Returns:
        Context dict with `events`, `current_event`, `is_proposal_active` and
        `active_nav`.
    """
    sphere_id = request.context.current_sphere_id
    events = request.services.sphere_panel.list_events(sphere_id)
    current_event = events[0] if events else None

    return {
        "events": events,
        "current_event": current_event,
        "is_proposal_active": (
            is_proposal_active(current_event) if current_event else False
        ),
        "active_nav": active_nav,
    }


def sphere_panel_context(
    request: MultiverseRequest, *, active_tab: str
) -> PanelContext:
    """Build sidebar + tabs context for a page inside Sphere settings.

    Returns:
        `sphere_panel_nav`'s keys plus the settings tabs (`active_tab`,
        `tab_urls`).
    """
    return sphere_panel_nav(request, active_nav="sphere-settings") | {
        "active_tab": active_tab,
        "tab_urls": {
            "general": reverse("multiverse:panel:sphere-settings"),
            "connections": reverse("multiverse:panel:connections"),
            "announcements": reverse("multiverse:panel:announcements"),
            "mcp": reverse("multiverse:panel:mcp-token"),
        },
    }
