# Enforces `Sphere.enabled_pages` at dispatch, not only in the navbar: a
# disabled page group must 404 on direct URL access. Keep this mixin leftmost
# in the MRO so the 404 wins over LoginRequiredMixin's login redirect — a
# redirect would leak that the page exists.
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, TypedDict, cast

from django.http import Http404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import View

from ludamus.pacts import SpherePage

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import SphereDTO


SPHERE_PAGE_LABELS = {
    SpherePage.EVENTS: _("Events"),
    SpherePage.ENCOUNTERS: _("Encounters"),
    SpherePage.TIMELINE: _("Timeline"),
}

SPHERE_PAGE_URL_NAMES = {
    SpherePage.EVENTS: "web:events",
    SpherePage.ENCOUNTERS: "web:notice-board:index",
    SpherePage.TIMELINE: "web:timeline",
}

# The sub-pages of a page group, by URL namespace. An event detail page lives
# under `chronology`, so the navbar still marks Events as current there.
SPHERE_PAGE_NAMESPACES = {
    "chronology": SpherePage.EVENTS,
    "event": SpherePage.EVENTS,
    "notice-board": SpherePage.ENCOUNTERS,
}

# The group landing pages carry no namespace of their own, only a url_name.
# Must stay consistent with SPHERE_PAGE_URL_NAMES above.
_LANDING_URL_NAMES = {"events": SpherePage.EVENTS, "timeline": SpherePage.TIMELINE}


class SpherePageNavItem(TypedDict):
    label: str
    url: str
    is_active: bool


def _active_sphere_page(request: HttpRequest) -> SpherePage | None:
    """Name the page group the current URL belongs to, if any."""
    if (match := request.resolver_match) is None:
        return None
    for namespace in match.namespaces:
        if page := SPHERE_PAGE_NAMESPACES.get(namespace):
            return page
    return _LANDING_URL_NAMES.get(match.url_name or "")


def sphere_page_nav(
    request: HttpRequest, sphere: SphereDTO | None
) -> list[SpherePageNavItem]:
    if sphere is None:
        return []
    active = _active_sphere_page(request)
    # Content served through the timeline while its own group is disabled
    # files under the Timeline tab — the only nav entry leading back to it.
    if (
        active is not None
        and active not in sphere.enabled_pages
        and SpherePage.TIMELINE in sphere.enabled_pages
    ):
        active = SpherePage.TIMELINE
    return [
        SpherePageNavItem(
            label=str(SPHERE_PAGE_LABELS[page]),
            url=reverse(SPHERE_PAGE_URL_NAMES[page]),
            is_active=page is active,
        )
        # Ordered by the enum, not by the sphere's list, so the navbar reads
        # the same everywhere however the setting was saved.
        for page in SpherePage
        if page in sphere.enabled_pages
    ]


class SpherePageRequiredMixin(View):
    required_sphere_page: ClassVar[SpherePage]
    # The timeline feed links into event and encounter content, so that content
    # must stay reachable when the timeline is the only enabled page. Group
    # landing pages opt out — each is the very page the setting disables.
    reachable_via_timeline: ClassVar[bool] = False

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        root_request = cast("RootRequest", request)
        sphere = root_request.services.sites.read(
            root_request.context.current_sphere_id
        )
        enabled = sphere.enabled_pages
        if self.required_sphere_page not in enabled and not (
            self.reachable_via_timeline and SpherePage.TIMELINE in enabled
        ):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class EventsPageRequiredMixin(SpherePageRequiredMixin):
    required_sphere_page = SpherePage.EVENTS
    reachable_via_timeline = True
