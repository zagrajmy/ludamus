"""What the command menu can find beyond its fixed commands.

One fragment of links, fetched when the menu first opens and searched in the
browser from then on. Everything in it belongs to the sphere being served:
what the visitor may create here, the events they manage here, and the
encounters they organize here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from ludamus.gates.web.django.access import has_panel_access
from ludamus.gates.web.django.create_options import create_options

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.gates.web.django.entities import RootRequest


@dataclass(frozen=True)
class MenuEntry:
    label: str
    href: str
    when: datetime


def _events(request: RootRequest) -> list[MenuEntry]:
    if not has_panel_access(request):
        return []
    events = request.services.sphere_panel.list_events(
        request.context.current_sphere_id
    )
    return [
        MenuEntry(
            label=event.name,
            href=reverse("panel:event-index", kwargs={"slug": event.slug}),
            when=event.start_time,
        )
        for event in events
    ]


def _encounters(request: RootRequest, *, user_id: int) -> list[MenuEntry]:
    encounters = request.services.encounters.list_organized(
        sphere_id=request.context.current_sphere_id, user_id=user_id
    )
    return [
        MenuEntry(
            label=encounter.title,
            href=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
            when=encounter.start_time,
        )
        for encounter in encounters
    ]


@require_GET
def command_menu_entries(request: RootRequest) -> TemplateResponse:
    user_id = request.context.current_user_id
    return TemplateResponse(
        request,
        "components/command-menu-entries.html",
        {
            "create_options": create_options(request, user_id=user_id),
            "events": _events(request),
            "encounters": (
                [] if user_id is None else _encounters(request, user_id=user_id)
            ),
        },
    )
