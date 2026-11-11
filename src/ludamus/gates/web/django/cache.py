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
    # NOTE: cache-control depends on request-time auth state, so it can't be a
    # static @method_decorator. TemplateView.get() funnels through
    # render_to_response(), so one override covers every view using the mixin.
    audience_cache_max_age: int

    def render_to_response(
        self, context: dict[str, Any], **response_kwargs: Any
    ) -> HttpResponse:
        response = super().render_to_response(context, **response_kwargs)
        return patch_audience_cache(
            response=response, request=self.request, max_age=self.audience_cache_max_age
        )
