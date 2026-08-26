# Enforces `Sphere.enabled_pages` at dispatch, not only in the navbar: a
# disabled page group must 404 on direct URL access. Keep this mixin leftmost
# in the MRO so the 404 wins over LoginRequiredMixin's login redirect — a
# redirect would leak that the page exists.
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from django.http import Http404
from django.views.generic.base import View

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import SpherePage


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
