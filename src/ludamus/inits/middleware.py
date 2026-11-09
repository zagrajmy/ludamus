import logging
from contextlib import suppress
from itertools import takewhile
from typing import TYPE_CHECKING, Protocol, TypeVar

from django.conf import settings
from django.utils.translation import get_supported_language_variant
from django.utils.translation.trans_real import parse_accept_lang_header

from ludamus.inits.dbos_scheduler import launch_scheduler
from ludamus.inits.services import Services
from ludamus.pacts.crowd import UserData

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ludamus.pacts.legacy import RootRequestProtocol

    class SessionProtocol(Protocol):
        """The slice of the Django session this middleware touches."""

        def get(self, key: str, default: list[int]) -> list[int]: ...
        def __setitem__(self, key: str, value: list[int]) -> None: ...

    class SessionRequestProtocol(RootRequestProtocol, Protocol):
        session: SessionProtocol

    class LanguageUserProtocol(Protocol):
        """The slice of `request.user` this middleware reads."""

        is_authenticated: bool
        language: str
        slug: str

    class LanguageRequestProtocol(RootRequestProtocol, Protocol):
        user: LanguageUserProtocol
        COOKIES: Mapping[str, str]
        headers: Mapping[str, str]


Response = TypeVar("Response")

logger = logging.getLogger(__name__)


SUBSCRIBED_SPHERES_SESSION_KEY = "subscribed_sphere_ids"


class SphereVisitSubscriptionMiddleware[Response]:
    """Subscribe a signed-in visitor to the sphere their request landed on.

    Ordered after RequestContextMiddleware, which resolved the sphere from the
    Host header, and run only for app requests (`AppMiddleware`), so
    `request.context` and `request.services` exist whenever this middleware
    acts. The session
    flag makes the warm path query-free; the insert itself never touches an
    existing row, so a muted subscription stays muted across visits and fresh
    sessions alike.
    """

    def __init__(
        self, get_response: Callable[[SessionRequestProtocol], Response]
    ) -> None:
        self.get_response: Callable[[SessionRequestProtocol], Response] = get_response

    def __call__(self, request: SessionRequestProtocol) -> Response:
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


class UserLanguageMiddleware[Response]:
    """Remember the language a signed-in user's browser asks for.

    Notifications to them are written in it, whoever raises them. A browser
    that names no supported language leaves it unrecorded, rather than
    recording LocaleMiddleware's LANGUAGE_CODE fallback. Ordered after the
    authentication and service middlewares. Compared against the user row
    the request already loaded, so it writes only when the language changes.
    """

    def __init__(
        self, get_response: Callable[[LanguageRequestProtocol], Response]
    ) -> None:
        self.get_response: Callable[[LanguageRequestProtocol], Response] = get_response

    def __call__(self, request: LanguageRequestProtocol) -> Response:
        _remember_language(request)
        return self.get_response(request)


def _remember_language(request: LanguageRequestProtocol) -> None:
    user = request.user
    if (
        user.is_authenticated
        and (language := _stated_language(request))
        and language != user.language
    ):
        logger.debug("User %s now browses in %s", user.slug, language)
        request.services.profile.update(user.slug, UserData(language=language))


def _stated_language(request: LanguageRequestProtocol) -> str | None:
    """Pick Django's request language, minus its LANGUAGE_CODE fallback.

    Same order as `get_language_from_request`: the cookie, then
    Accept-Language by quality, stopping at `*`.
    """
    cookie = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME, "")
    accepted = parse_accept_lang_header(request.headers.get("accept-language", ""))
    named = takewhile(lambda code: code != "*", (code for code, _ in accepted))
    for code in (cookie, *named):
        with suppress(LookupError):
            return get_supported_language_variant(code).lower()
    return None


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
        request.services = Services()
        return self.get_response(request)
