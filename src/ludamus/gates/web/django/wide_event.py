"""One context-rich log event per request, instead of a trail of narration.

The event answers "what happened to this request" in a single line: who, on
which sphere, which route, how long, how many queries, and if it failed, how.
Outermost in MIDDLEWARE so the clock covers the whole stack and a fault in
any inner middleware still shows up as a 500 event.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextvars import ContextVar
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.db import connection
from django.utils.translation import get_language

from ludamus.links.analytics import identity, redaction

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.backends.utils import CursorWrapper
    from django.http import HttpRequest, HttpResponseBase

    from ludamus.pacts import RequestContext

type Field = str | int | float | bool | None
type WideEvent = dict[str, Field]
# What Django hands an execute wrapper: sql, params, many, context.
type QueryArgument = (
    str
    | bool
    | Sequence[Field]
    | Mapping[str, Field]
    | Mapping[str, BaseDatabaseWrapper | CursorWrapper]
    | None
)

SKIPPED_PREFIXES = (settings.STATIC_URL, "/healthz/")

# The event under construction for the request this thread is serving. A
# context variable rather than a request attribute so a later caller deeper
# than the view (a service in mills) can add to it without seeing Django.
_event: ContextVar[WideEvent | None] = ContextVar("wide_event", default=None)


class WideEventMiddleware:
    logger: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if request.path.startswith(SKIPPED_PREFIXES):
            return self.get_response(request)

        event: WideEvent = {
            # Cloudflare stamps every proxied request; the same id is what
            # the user sees on an edge error page and what its logs are
            # keyed by, so one search covers edge, origin and the report.
            "ray_id": request.headers.get("CF-Ray") or uuid.uuid4().hex,
            # Which build and which of the gunicorn workers served it, so a
            # regression lines up with a deploy and a wedged worker with its
            # requests.
            "environment": identity.environment(),
            "commit": settings.COMMIT_SHA,
            "worker": os.getpid(),
            "method": request.method,
            "path": redaction.safe_path(request.path_info),
            "htmx": request.headers.get("HX-Request") == "true",
        }
        token = _event.set(event)
        queries = _QueryMeter()
        started = time.perf_counter()
        try:
            with connection.execute_wrapper(queries):
                response = self.get_response(request)
        finally:
            _event.reset(token)
            event["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            event["db_queries"] = queries.count
            event["db_ms"] = round(queries.seconds * 1000, 1)

        event["status"] = response.status_code
        event.setdefault(
            "outcome",
            (
                "error"
                if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
                else "success"
            ),
        )
        if (match := request.resolver_match) is not None:
            event["view"] = match.view_name
            event["route"] = match.route
        event["language"] = get_language()
        context: RequestContext | None = getattr(request, "context", None)
        event["sphere_id"] = context.current_sphere_id if context else None
        event["user_id"] = context.current_user_id if context else None

        self.logger.info(
            "%s %s %s %sms",
            event["method"],
            event["path"],
            event["status"],
            event["duration_ms"],
            extra=event,
        )
        return response

    @staticmethod
    def process_exception(_request: HttpRequest, exception: Exception) -> None:
        if (event := _event.get()) is not None:
            event["outcome"] = "error"
            event["error_type"] = type(exception).__name__
            event["error_message"] = str(exception)


class _QueryMeter:
    """Counts the request's queries on the default connection and times them."""

    def __init__(self) -> None:
        self.count = 0
        self.seconds = 0.0

    def __call__[T](self, execute: Callable[..., T], *query: QueryArgument) -> T:
        self.count += 1
        started = time.perf_counter()
        try:
            return execute(*query)
        finally:
            self.seconds += time.perf_counter() - started
