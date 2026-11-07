from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.generic.base import TemplateResponseMixin

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

EVENT_PAGE_CACHE_SECONDS = 180


def patch_audience_cache(
    *, response: HttpResponse, request: HttpRequest, max_age: int
) -> HttpResponse:
    patch_vary_headers(response, ["Cookie"])
    if request.user.is_authenticated:
        patch_cache_control(response, private=True, max_age=max_age)
    else:
        patch_cache_control(response, public=True, max_age=max_age)
    return response


class AudienceCachedResponseMixin(TemplateResponseMixin):
    # Shared by EventsPageView/EventPageView: cache-control depends on
    # request-time auth state (private for signed-in users, public for
    # anonymous), so it can't be a static @method_decorator like the rest of
    # this file's caching. TemplateView.get()/DetailView.get() both funnel
    # through render_to_response(), so patching there (rather than
    # overriding get() on each view) covers both with one Any-typed override.
    audience_cache_max_age: int

    def render_to_response(
        self, context: dict[str, Any], **response_kwargs: Any
    ) -> HttpResponse:
        response = super().render_to_response(context, **response_kwargs)
        return patch_audience_cache(
            response=response, request=self.request, max_age=self.audience_cache_max_age
        )
