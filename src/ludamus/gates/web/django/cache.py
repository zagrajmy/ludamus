from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING

from django.contrib.messages import get_messages
from django.template.response import SimpleTemplateResponse
from django.utils.cache import patch_cache_control, patch_vary_headers

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponseBase

    type View = Callable[..., HttpResponseBase]

EVENT_PAGE_CACHE_SECONDS = 180


def _is_shareable(request: HttpRequest) -> bool:
    # SAFETY: a shared cache hands one copy to every visitor. A rendered CSRF
    # token unmasks to this browser's CSRF secret; a session or a flash
    # message carries this visitor's state. Any of them keeps it private.
    return not (
        request.user.is_authenticated
        or request.META.get("CSRF_COOKIE_NEEDS_UPDATE")
        or not request.session.is_empty()
        or len(get_messages(request))
    )


def patch_audience_cache(
    *, response: HttpResponseBase, request: HttpRequest, max_age: int
) -> HttpResponseBase:
    patch_vary_headers(response, ["Cookie"])
    if _is_shareable(request):
        patch_cache_control(response, public=True, max_age=max_age)
    else:
        patch_cache_control(response, private=True, max_age=max_age)
    return response


def audience_cache(*, max_age: int) -> Callable[[View], View]:
    def decorator(view: View) -> View:
        @wraps(view)
        def wrapped(
            request: HttpRequest, /, *args: str, **kwargs: str
        ) -> HttpResponseBase:
            response = view(request, *args, **kwargs)

            def patch(rendered: HttpResponseBase) -> HttpResponseBase:
                return patch_audience_cache(
                    response=rendered, request=request, max_age=max_age
                )

            # NOTE: a TemplateResponse renders after the view returns, and only
            # rendering tells whether the page used a CSRF token or messages.
            if isinstance(response, SimpleTemplateResponse) and not (
                response.is_rendered
            ):
                response.add_post_render_callback(patch)
                return response
            return patch(response)

        return wrapped

    return decorator
