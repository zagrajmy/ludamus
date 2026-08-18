from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from django.apps import AppConfig
from django.core.signals import got_request_exception

from ludamus.links import analytics

if TYPE_CHECKING:
    from django.dispatch import Signal
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def report_request_exception(*, request: HttpRequest, **_kwargs: Signal | None) -> None:
    # Django converts a view exception into a response before it propagates
    # back through the middleware stack, so a middleware-based hook never sees
    # it. This signal does.
    exception = sys.exc_info()[1]
    if exception is None:
        return
    try:
        analytics.report_exception(exception, request)
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

    name = "ludamus.links"
    label = "analytics"

    def ready(self) -> None:
        got_request_exception.connect(
            report_request_exception, dispatch_uid=f"{self.label}.request_exception"
        )
