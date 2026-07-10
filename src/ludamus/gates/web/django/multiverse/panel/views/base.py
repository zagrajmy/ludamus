"""Shared helpers for multiverse panel views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.urls import reverse

from ludamus.mills import is_proposal_active

if TYPE_CHECKING:
    from ludamus.gates.web.django.multiverse.access import MultiverseRequest


def sphere_panel_context(
    request: MultiverseRequest, *, active_tab: str
) -> dict[str, Any]:
    """Build sidebar + tabs context for a sphere-scoped panel page.

    `current_event` defaults to the most recent sphere event so the event
    panel sidebar (rendered from `panel/base.html`) has something to link to.
    When the sphere has no events the sidebar gracefully hides event-scoped
    items.

    Returns:
        Context dict with sidebar (`events`, `current_event`,
        `is_proposal_active`, `active_nav`) and tabs (`is_general_tab`,
        `is_connections_tab`, `tab_urls`) keys.
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
        "active_nav": "sphere-settings",
        "is_general_tab": active_tab == "general",
        "is_connections_tab": active_tab == "connections",
        "is_announcements_tab": active_tab == "announcements",
        "is_mcp_tab": active_tab == "mcp",
        "tab_urls": {
            "general": reverse("multiverse:panel:sphere-settings"),
            "connections": reverse("multiverse:panel:connections"),
            "announcements": reverse("multiverse:panel:announcements"),
            "mcp": reverse("multiverse:panel:mcp-token"),
        },
    }
