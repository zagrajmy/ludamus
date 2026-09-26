from typing import TYPE_CHECKING, Protocol

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpRequest, HttpResponseBase, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext as _

from ludamus.pacts import (
    AuthenticatedRequestContext,
    NotFoundError,
    RedirectError,
    RequestContext,
)
from ludamus.pacts.ids import UserId
from ludamus.pacts.multiverse import SphereVisibility

if TYPE_CHECKING:
    from ludamus.pacts import DependencyInjectorProtocol
    from ludamus.pacts.services import ServicesProtocol


class RootRepositoryRequest(HttpRequest):
    context: RequestContext
    di: DependencyInjectorProtocol
    services: ServicesProtocol


# Paths a private sphere still serves to strangers: signing in, and the MCP
# endpoints, which authenticate by token and scope themselves to its sphere.
PRIVATE_SPHERE_OPEN_PREFIXES = ("/crowd/", "/auth-error/", "/mcp/", "/.well-known/")


class _GetResponseCallable(Protocol):
    def __call__(self, request: HttpRequest, /) -> HttpResponseBase: ...


class RequestContextMiddleware:
    def __init__(self, get_response: _GetResponseCallable) -> None:
        self.get_response = get_response

    def __call__(self, request: RootRepositoryRequest) -> HttpResponseBase:
        if request.path.startswith(settings.MIDDLEWARE_SKIP_PREFIXES):
            return self.get_response(request)

        sphere_repository = request.di.uow.spheres
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
            )
        else:
            request.context = RequestContext(
                root_sphere_id=root_sphere.pk,
                current_sphere_id=current_sphere.pk,
                root_site_id=root_sphere.site.pk,
                current_site_id=current_sphere.site.pk,
            )

        if current_sphere.visibility is SphereVisibility.PRIVATE and not (
            request.path.startswith(PRIVATE_SPHERE_OPEN_PREFIXES)
        ):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            # A stranger gets the same answer as for a sphere that does not
            # exist, so a private sphere's name and events never leak.
            if (
                not request.user.is_superuser
                and request.services.sphere_panel.manager_role(
                    current_sphere.pk, request.user.slug
                )
                is None
            ):
                raise Http404

        return self.get_response(request)


class RedirectErrorMiddleware:
    def __init__(self, get_response: _GetResponseCallable) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        return self.get_response(request)

    @staticmethod
    def process_exception(  # pylint: disable=no-self-use
        request: HttpRequest, exception: Exception  # pylint: disable=unused-argument
    ) -> HttpResponseBase | None:
        if isinstance(exception, RedirectError):
            if exception.error:
                messages.error(request, exception.error)
            if exception.warning:
                messages.warning(request, exception.warning)
            return HttpResponseRedirect(exception.url)

        return None
