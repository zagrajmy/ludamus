from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404

from ludamus.gates.web.django.access import has_panel_access
from ludamus.pacts.multiverse import SphereVisibility

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponseBase

    from ludamus.gates.web.django.entities import RootRequest


class _GetResponseCallable(Protocol):
    def __call__(self, request: HttpRequest, /) -> HttpResponseBase: ...


class PrivateSphereMiddleware:
    """Open a private sphere only to the people who hold a role in it."""

    def __init__(self, get_response: _GetResponseCallable) -> None:
        self.get_response = get_response

    def __call__(self, request: RootRequest) -> HttpResponseBase:
        if (
            request.path.startswith(settings.PRIVATE_SPHERE_OPEN_PREFIXES)
            or request.context.current_sphere_visibility is not SphereVisibility.PRIVATE
        ):
            return self.get_response(request)
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        # A stranger gets the same answer as for a sphere that does not exist,
        # so a private sphere's name and events never leak.
        if not has_panel_access(request):
            raise Http404
        return self.get_response(request)
