from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.contrib import messages
from django.http import (  # Django
    HttpRequest,
    HttpResponse,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)
from django.template.response import TemplateResponse
from django.urls import Resolver404, resolve, reverse
from django.utils.translation import gettext as _

from ludamus.mills.url_recovery import strip_trailing_junk
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from ludamus.pacts import RootRequestProtocol

_EVENT_VIEW_NAME = "web:chronology:event"

_EVENT_MISSING = "missing"
_EVENT_UNPUBLISHED = "unpublished"
_EVENT_PUBLISHED = "published"


def _event_slug(path: str) -> str | None:
    try:
        match = resolve(path)
    except Resolver404:
        return None
    if match.view_name == _EVENT_VIEW_NAME:
        return match.kwargs.get("slug")
    return None


def _event_state(request: RootRequestProtocol, slug: str) -> str:
    try:
        event = request.services.events.read_by_slug(
            request.context.current_sphere_id, slug
        )
    except NotFoundError:
        return _EVENT_MISSING
    published = (
        event.publication_time is not None
        and event.publication_time <= datetime.now(tz=UTC)
    )
    return _EVENT_PUBLISHED if published else _EVENT_UNPUBLISHED


def _recover_from_404(request: HttpRequest) -> HttpResponse | None:
    # Only safe, idempotent navigations are recovered, and only once the
    # request context middleware has resolved a sphere for this host.
    if request.method not in {"GET", "HEAD"}:
        return None
    if not hasattr(request, "services") or not hasattr(request, "context"):
        return None

    cleaned = strip_trailing_junk(request.path)
    # A cleaned path that resolves to an event means the original link had
    # stray trailing characters (a dot, a closing paren, an emoji that a
    # chat/social autolinker swallowed). Otherwise fall back to the slug of
    # the clean-but-unresolved event URL that originally 404'd.
    slug_from_cleaned = _event_slug(cleaned) if cleaned is not None else None
    if (slug := slug_from_cleaned or _event_slug(request.path)) is None:
        return None

    root_request = cast("RootRequestProtocol", request)
    state = _event_state(root_request, slug)

    # A junk link to a real, public event: send them on to the clean,
    # canonical event URL with a permanent redirect.
    if slug_from_cleaned is not None and state == _EVENT_PUBLISHED:
        return HttpResponsePermanentRedirect(
            reverse(_EVENT_VIEW_NAME, kwargs={"slug": slug})
        )

    # Missing and unpublished events return the same response on purpose, so a
    # 404 never reveals whether an unannounced event exists. The visitor
    # reached the right sphere, so send them to the events list with a neutral
    # explanation rather than dropping them on the home page with no context.
    # (A clean URL to a public event renders normally and never reaches here.)
    if state in {_EVENT_MISSING, _EVENT_UNPUBLISHED}:
        messages.info(request, _("That event isn't available."))
        return HttpResponseRedirect(reverse("web:events"))

    return None


def custom_404(
    request: HttpRequest, exception: Exception | None  # noqa: ARG001
) -> HttpResponse:
    if (recovered := _recover_from_404(request)) is not None:
        return recovered

    context = {
        "error_code": HTTPStatus.NOT_FOUND,
        "title": _("Page not found"),
        "message": _("We couldn't find the page you were looking for."),
        "subtitle": _(
            "The link may be broken or the page may have moved. "
            "Use the buttons below to go back or return to the home page."
        ),
        "icon": "question-mark-circle",
    }

    response = TemplateResponse(request, "404_dynamic.html", context)
    response.status_code = 404
    return response


def custom_500(request: HttpRequest) -> TemplateResponse:
    context = {
        "error_code": HTTPStatus.INTERNAL_SERVER_ERROR,
        "title": _("Something went wrong on our side"),
        "message": _("An unexpected error stopped this page from loading."),
        "subtitle": (
            _(
                "Please try again in a moment. If it keeps happening, "
                "let us know at %(support_email)s."
            )
            % {"support_email": settings.SUPPORT_EMAIL}
        ),
        "icon": "exclamation-triangle",
    }

    response = TemplateResponse(request, "500_dynamic.html", context)
    response.status_code = 500
    return response
