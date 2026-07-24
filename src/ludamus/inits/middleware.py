from typing import TYPE_CHECKING, TypeVar

from django.conf import settings

from ludamus.inits.dbos_scheduler import launch_scheduler
from ludamus.inits.services import Services

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts import RootRequestProtocol


Response = TypeVar("Response")


class ServiceInjectionMiddleware[Response]:
    """Attach `request.services` — the gate-facing service namespace.

    Runs in parallel with RepositoryInjectionMiddleware during the strangler-fig
    migration. A view either uses `request.di.uow.*` (legacy) or
    `request.services.*` (migrated) — never both shapes in the same view.
    """

    def __init__(self, get_response: Callable[[RootRequestProtocol], Response]) -> None:
        self.get_response: Callable[[RootRequestProtocol], Response] = get_response
        # Handler construction is a serving process's startup moment (per
        # gunicorn worker, post-fork; never management commands): start the
        # in-system DBOS scheduler so cron workflows run without traffic.
        launch_scheduler()

    def __call__(self, request: RootRequestProtocol) -> Response:
        if not request.path.startswith(settings.MIDDLEWARE_SKIP_PREFIXES):
            request.services = Services()

        return self.get_response(request)
