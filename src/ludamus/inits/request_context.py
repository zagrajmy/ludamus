from typing import TYPE_CHECKING, Protocol

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponseBase, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext as _

from ludamus.inits.repositories import Repositories
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.ids import UserId
from ludamus.pacts.services import AuthenticatedRequestContext, RequestContext

if TYPE_CHECKING:
    from ludamus.pacts.services import ServicesProtocol


class ContextRequest(HttpRequest):
    context: RequestContext
    services: ServicesProtocol


class _GetResponseCallable(Protocol):
    def __call__(self, request: HttpRequest, /) -> HttpResponseBase: ...


class RequestContextMiddleware:
    def __init__(self, get_response: _GetResponseCallable) -> None:
        self.get_response = get_response

    def __call__(self, request: ContextRequest) -> HttpResponseBase:
        if request.path.startswith(settings.MIDDLEWARE_SKIP_PREFIXES):
            return self.get_response(request)

        sphere_repository = Repositories().spheres
        root_sphere = sphere_repository.read_by_domain(settings.ROOT_DOMAIN)
        try:
            # On the root domain (the common case) the current sphere IS the
            # root sphere; skip the second identical lookup.
            current_sphere = (
                root_sphere
                if request.get_host() == settings.ROOT_DOMAIN
                else sphere_repository.read_by_domain(request.get_host())
            )
        except NotFoundError:
            host = request.get_host().split(":", 1)[0]
            if settings.ENV == "development" and (
                host == "127.0.0.1" or host.endswith((".localhost", ".local"))
            ):
                current_sphere = root_sphere
            else:
                url = f"{request.scheme}://{settings.ROOT_DOMAIN}{reverse('web:index')}"
                messages.error(request, _("Sphere not found"))
                return HttpResponseRedirect(url)

        if hasattr(request, "user") and request.user.is_authenticated:
            request.context = AuthenticatedRequestContext(
                root_sphere_id=root_sphere.pk,
                current_sphere_id=current_sphere.pk,
                root_site_id=root_sphere.site.pk,
                current_site_id=current_sphere.site.pk,
                current_user_slug=request.user.slug,
                current_user_id=UserId(request.user.pk),
                current_sphere_visibility=current_sphere.visibility,
            )
        else:
            request.context = RequestContext(
                root_sphere_id=root_sphere.pk,
                current_sphere_id=current_sphere.pk,
                root_site_id=root_sphere.site.pk,
                current_site_id=current_sphere.site.pk,
                current_sphere_visibility=current_sphere.visibility,
            )

        return self.get_response(request)
