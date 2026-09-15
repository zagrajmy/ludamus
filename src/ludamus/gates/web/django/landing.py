from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.response import TemplateResponse

from ludamus.gates.web.django.events import EventsPageView

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest


def index_page(request: RootRequest) -> HttpResponse:
    """Serve the sphere root: the feed, or the pitch when there is no feed.

    Returns:
        The landing page for a visitor who has not signed in on the root
        sphere — they came looking for the product, not for a programme —
        and the events feed for everyone else. A signed-in visitor always
        gets the feed, which is why no private encounter of theirs ever
        lands on the marketing page.
    """
    context = request.context
    if (
        context.current_sphere_id != context.root_sphere_id
        or request.user.is_authenticated
    ):
        return EventsPageView.as_view()(request)
    landing = request.services.landing
    return TemplateResponse(
        request,
        ["landing_page.html"],
        {"stats": landing.stats(), "conventions": landing.conventions()},
    )
