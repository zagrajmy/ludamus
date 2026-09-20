from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.response import TemplateResponse

from ludamus.gates.web.django.dashboard import dashboard_page
from ludamus.gates.web.django.events import EventsPageView

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest

# How many open encounters the landing lists before sending you to the feed.
LANDING_ENCOUNTERS = 4


def index_page(request: RootRequest) -> HttpResponse:
    """Serve the sphere root: its programme, or — on zagrajmy.net — you.

    Returns:
        The events feed on every sphere that runs a programme, since its root
        is that programme. On the root sphere, which runs none, the pitch for
        a visitor and their own dashboard once they are signed in.
    """
    context = request.context
    if context.current_sphere_id != context.root_sphere_id:
        return EventsPageView.as_view()(request)
    if (user_id := context.current_user_id) is not None:
        return dashboard_page(request, user_id=user_id)
    return landing_page(request)


def landing_page(request: RootRequest) -> HttpResponse:
    """Render the pitch, with the live evidence behind it.

    Returns:
        The landing page: the conventions that run on Zagrajmy, and the open
        encounters the copy claims are already happening.
    """
    context = request.context
    landing = request.services.landing
    # The pitch claims people are already playing; this is that claim's
    # evidence. A signed-in visitor also sees the ones they organise or hold
    # an RSVP to, the same as anywhere else.
    encounters = request.services.encounters.list_feed(
        sphere_id=context.current_sphere_id, user_id=context.current_user_id
    )
    return TemplateResponse(
        request,
        ["landing_page.html"],
        {
            "stats": landing.stats(),
            "conventions": landing.conventions(),
            "encounters": encounters.upcoming[:LANDING_ENCOUNTERS],
            # A sphere with encounters off 404s the create route for every
            # visitor, signed in or not; the "Run an Encounter" CTA must not
            # send anyone into that.
            "encounters_enabled": request.services.encounters.enabled(
                context.current_sphere_id
            ),
        },
    )
