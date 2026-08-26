# Enforces `Sphere.enabled_pages` at dispatch, not only in the navbar: a
# disabled page group must 404 on direct URL access. Keep this mixin leftmost
# in the MRO so the 404 wins over LoginRequiredMixin's login redirect — a
# redirect would leak that the page exists.
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from django.http import Http404
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import View

from ludamus.pacts import SpherePage

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from ludamus.gates.web.django.entities import RootRequest


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


class SpherePageRequiredMixin(View):
    required_sphere_page: ClassVar[SpherePage]

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        root_request = cast("RootRequest", request)
        sphere = root_request.services.sites.read(
            root_request.context.current_sphere_id
        )
        if self.required_sphere_page not in sphere.enabled_pages:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class EventsPageRequiredMixin(SpherePageRequiredMixin):
    required_sphere_page = SpherePage.EVENTS
