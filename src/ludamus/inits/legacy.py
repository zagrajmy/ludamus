from functools import cached_property
from typing import TYPE_CHECKING, TypeVar

from django.conf import settings

from ludamus.links.cache import DjangoCache
from ludamus.links.db.django.uow import UnitOfWork
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import CacheProtocol, DependencyInjectorProtocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts import RootRequestProtocol


Response = TypeVar("Response")


class DependencyInjector(DependencyInjectorProtocol):
    """Container for all request-scoped dependencies.

    Usage:
        request.di.uow.enrollments
        request.di.cache
    """

    @cached_property
    def uow(self) -> UnitOfWork:
        return UnitOfWork()

    @cached_property
    def cache(self) -> CacheProtocol:
        return DjangoCache()

    @staticmethod
    def gravatar_url(email: str) -> str | None:
        return gravatar_url(email)


class RepositoryInjectionMiddleware[Response]:
    """This is weird.

    It's a Django middleware, but it's out of the django framework
    code because there's no better way to inject dependencies to django views.
    Pretend you didn't see it and proceed with your work ;)
    """

    def __init__(self, get_response: Callable[[RootRequestProtocol], Response]) -> None:
        self.get_response: Callable[[RootRequestProtocol], Response] = get_response

    def __call__(self, request: RootRequestProtocol) -> Response:
        if not request.path.startswith(settings.MIDDLEWARE_SKIP_PREFIXES):
            request.di = DependencyInjector()

        return self.get_response(request)
