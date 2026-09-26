from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import RedirectView

from ludamus.gates.web.django.dashboard import dashboard_page
from ludamus.gates.web.django.events import EventsPageView

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest

# How many open encounters the landing lists before sending you to the feed.
LANDING_ENCOUNTERS = 4

# The event page the pitch sends a visitor to as its proof. Kapitularz runs
# on its own sphere, so the production landing links across domains.
SHOWCASE_EVENT_URL = "https://kapitularz.zagrajmy.net/"

# Where organizers write to start an event. Not SUPPORT_EMAIL: that one takes
# account and data requests, this one is the sales conversation.
CONTACT_EMAIL = "kontakt@zagrajmy.net"

# Testimonial authors aren't users here, so each gets the fields the avatar
# component reads.
MAMERT = {"name": "Mamert"}

# The old homes of the feed, now the sphere root. Shared links carry filters
# and UTM tags, so the query string rides along.
legacy_feed_redirect = RedirectView.as_view(
    pattern_name="web:index", permanent=True, query_string=True
)


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
    encounters = request.services.encounters.list_upcoming(
        sphere_id=context.current_sphere_id,
        user_id=context.current_user_id,
        limit=LANDING_ENCOUNTERS,
    )
    return TemplateResponse(
        request,
        ["landing_page.html"],
        {
            "stats": landing.stats(),
            "conventions": landing.conventions(),
            "encounters": encounters,
            # A sphere with encounters off 404s the create route for every
            # visitor, signed in or not; the "Run an Encounter" CTA must not
            # send anyone into that.
            "encounters_enabled": request.services.encounters.enabled(
                context.current_sphere_id
            ),
            "showcase_url": _showcase_url(request),
            "contact_email": CONTACT_EMAIL,
            "mamert": MAMERT,
        },
    )


def _showcase_url(request: RootRequest) -> str:
    # Staging has no Kapitularz of its own, and its root sphere is where the
    # seeded events live, so the pitch shows one of those instead of sending
    # a tester off to production. A staging root sphere with nothing
    # published yet still gets the production page rather than a 404.
    if settings.IS_STAGING:
        slug = request.services.landing.showcase_slug(request.context.root_sphere_id)
        if slug is not None:
            return reverse("web:chronology:event", kwargs={"slug": slug})
    return SHOWCASE_EVENT_URL


def about_page(request: RootRequest) -> HttpResponse:
    """Render what Zagrajmy is, who runs it, and the facts behind the claims.

    Returns:
        The about page, with the live counts and conventions its key facts
        cite, so the numbers never go stale in the copy. On a convention's
        domain, a permanent redirect to the root domain's copy: the page is
        about Zagrajmy, and one address keeps crawlers from indexing a
        duplicate under every sphere's name.
    """
    context = request.context
    if context.current_sphere_id != context.root_sphere_id:
        root_domain = request.services.sites.read(context.root_sphere_id).site.domain
        return HttpResponsePermanentRedirect(
            f"{request.scheme}://{root_domain}{reverse('about')}"
        )
    landing = request.services.landing
    return TemplateResponse(
        request,
        ["about.html"],
        {
            "stats": landing.stats(),
            "conventions": landing.conventions(),
            "contact_email": CONTACT_EMAIL,
        },
    )
