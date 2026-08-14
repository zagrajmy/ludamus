# multiverse-specific.
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from django.urls import reverse

from ludamus.gates.web.django.panel import PanelNavContext
from ludamus.mills.event import is_proposal_active

SphereTab = Literal["general", "announcements", "connections"]

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
        },
    }
