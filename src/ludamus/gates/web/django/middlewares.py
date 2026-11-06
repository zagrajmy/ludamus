from typing import TYPE_CHECKING

from django.conf import settings
from django.core.handlers.exception import convert_exception_to_response
from django.http import HttpResponseBase
from django.utils.module_loading import import_string

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from django.http import HttpRequest


class PermissionsPolicyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        response = self.get_response(request)
        response["Permissions-Policy"] = settings.PERMISSIONS_POLICY
        return response


class AppMiddleware:
    """Run `APP_MIDDLEWARE` for app requests only, behind one prefix check.

    Static files, the admin, the health check and the debug tools need no
    services, no sphere and no visitor bookkeeping. The middlewares that supply
    those are built into a chain of their own, and a request whose path is in
    `MIDDLEWARE_SKIP_PREFIXES` bypasses the whole chain, so none of them has to
    ask again.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response
        app: Callable[[HttpRequest], HttpResponseBase | Awaitable[HttpResponseBase]]
        app = get_response
        for dotted_path in reversed(settings.APP_MIDDLEWARE):
            app = convert_exception_to_response(import_string(dotted_path)(app))
        self.app = app

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if request.path.startswith(settings.MIDDLEWARE_SKIP_PREFIXES):
            return self.get_response(request)
        response = self.app(request)
        if not isinstance(response, HttpResponseBase):
            msg = "APP_MIDDLEWARE must be synchronous, as the WSGI handler is."
            raise TypeError(msg)
        return response
