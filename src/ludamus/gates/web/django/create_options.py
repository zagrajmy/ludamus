"""What a visitor may start from a feed: an event, an encounter, both or none.

The feed's create control renders whatever this returns: nothing for no
option, a direct link for one, and a dialog that asks which for two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.access import panel_access
from ludamus.pacts.sphere import Capability

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import RootRequest


@dataclass(frozen=True)
class CreateOption:
    key: str
    href: str
    button_label: _StrPromise
    title: _StrPromise
    description: _StrPromise
    icon: str


def event_option() -> CreateOption:
    return CreateOption(
        key="event",
        href=reverse("panel:event-create"),
        button_label=_("Create event"),
        title=_("Event"),
        description=_(
            "For a convention or a bigger meetup. Collect program proposals"
            " and build a timetable."
        ),
        icon="calendar-days",
    )


def encounter_option() -> CreateOption:
    return CreateOption(
        key="encounter",
        href=reverse("web:notice-board:create"),
        button_label=_("Create encounter"),
        title=_("Encounter"),
        description=_(
            "Just a description, a time and a place. Best for online RPG"
            " sessions, game jams and freeform meetups."
        ),
        icon="user-group",
    )


def create_options(
    request: RootRequest, *, user_id: int | None
) -> tuple[CreateOption, ...]:
    """List what ``user_id`` may create in the current sphere, event first.

    An event needs the panel's write capability, the same check the panel's
    event form makes before it saves, and a sphere other than the root one,
    which runs no programme of its own. That last rule shapes this control
    only; the panel itself does not refuse the root sphere. Panel access is
    always the request's signed-in user's, as the panel's own is. An
    encounter follows the sphere's encounters policy for ``user_id``.

    Returns:
        The options in the order the dialog shows them.
    """
    context = request.context
    options: list[CreateOption] = []
    if context.current_sphere_id != context.root_sphere_id and panel_access(
        request
    ).allows(Capability.PANEL_WRITE):
        options.append(event_option())
    if user_id is not None and request.services.encounters.can_create(
        sphere_id=context.current_sphere_id, user_id=user_id
    ):
        options.append(encounter_option())
    return tuple(options)
