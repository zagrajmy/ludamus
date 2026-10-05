from typing import TYPE_CHECKING, Protocol, TypeVar

from django.conf import settings

from ludamus.inits.dbos_scheduler import launch_scheduler
from ludamus.inits.services import Services

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts import RootRequestProtocol

    class SessionProtocol(Protocol):
        """The slice of the Django session this middleware touches."""

        def get(self, key: str, default: list[int]) -> list[int]: ...
        def __setitem__(self, key: str, value: list[int]) -> None: ...

    class SessionRequestProtocol(RootRequestProtocol, Protocol):
        session: SessionProtocol


Response = TypeVar("Response")


SUBSCRIBED_SPHERES_SESSION_KEY = "subscribed_sphere_ids"


class SphereVisitSubscriptionMiddleware[Response]:
    """Subscribe a signed-in visitor to the sphere their request landed on.

    Ordered after RequestContextMiddleware, which resolved the sphere from the
    Host header (and skips the same prefixes skipped here, so `request.context`
    and `request.services` exist whenever this middleware acts). The session
    flag makes the warm path query-free; the insert itself never touches an
    existing row, so a muted subscription stays muted across visits and fresh
    sessions alike.
    """

    def __init__(
        self, get_response: Callable[[SessionRequestProtocol], Response]
    ) -> None:
        self.get_response: Callable[[SessionRequestProtocol], Response] = get_response

    def __call__(self, request: SessionRequestProtocol) -> Response:
        if not request.path.startswith(settings.MIDDLEWARE_SKIP_PREFIXES):
            _subscribe_visit(request)

        return self.get_response(request)


def _subscribe_visit(request: SessionRequestProtocol) -> None:
    if (user_id := request.context.current_user_id) is None:
        return
    sphere_id = request.context.current_sphere_id
    seen = request.session.get(SUBSCRIBED_SPHERES_SESSION_KEY, [])
    if sphere_id not in seen:
        request.services.notification_subscriptions.subscribe_sphere_visit(
            user_id=user_id, sphere_id=sphere_id
        )
        request.session[SUBSCRIBED_SPHERES_SESSION_KEY] = [*seen, sphere_id]


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
