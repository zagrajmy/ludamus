from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from django.apps import AppConfig
from django.core.signals import got_request_exception

from ludamus.links.analytics import reporting

if TYPE_CHECKING:
    from django.dispatch import Signal
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def report_request_exception(*, request: HttpRequest, **_kwargs: Signal | None) -> None:
    # process_exception() would see a view raising, and posthog's own
    # PosthogContextMiddleware uses exactly that. This signal is wider: it also
    # fires for middleware that raises, and again when the 500 handler itself
    # fails — the cases _distinct_id() is written to survive.
    if (exception := sys.exc_info()[1]) is None:
        return
    try:
        reporting.report_exception(exception, request)
    except Exception:
        # send(), not send_robust(): anything raising here would escape
        # handle_uncaught_exception and replace the 500 page with a traceback.
        logger.exception("Could not report an exception to PostHog")


class AnalyticsConfig(AppConfig):
    """Owns the signal wiring for fault reporting.

    An app of its own rather than a hook in WebGatesConfig: gates may not
    import links, and ludamus.inits cannot be an app because its __init__
    re-exports legacy, which imports models before the registry is ready.
    """

    name = "ludamus.links.analytics"
    label = "analytics"

    def ready(self) -> None:
        got_request_exception.connect(
            report_request_exception, dispatch_uid=f"{self.label}.request_exception"
        )
