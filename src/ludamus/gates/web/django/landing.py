from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.response import TemplateResponse

from ludamus.gates.web.django.events import EventsPageView

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest


def index_page(request: RootRequest) -> HttpResponse:
    """Serve the sphere root: the pitch on zagrajmy.net, the feed elsewhere.

    Returns:
        The landing page for the root sphere, whose visitors are looking for
        the product rather than for a programme, and the events feed for
        every other sphere, whose root is its programme.
    """
    context = request.context
    if context.current_sphere_id != context.root_sphere_id:
        return EventsPageView.as_view()(request)
    landing = request.services.landing
    return TemplateResponse(
        request,
        ["landing_page.html"],
        {"stats": landing.stats(), "conventions": landing.conventions()},
    )
