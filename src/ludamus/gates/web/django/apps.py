import logging
import sys
from importlib import import_module
from typing import TYPE_CHECKING

from django.apps import AppConfig
from django.core.signals import got_request_exception

from ludamus.links import posthog

if TYPE_CHECKING:
    from django.dispatch import Signal
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def report_request_exception(*, request: HttpRequest, **_kwargs: Signal | type) -> None:
    # Django converts a view exception into a response before it propagates
    # back through the middleware stack, so a middleware-based hook never sees
    # it. This signal does.
    exception = sys.exc_info()[1]
    if exception is None:
        return
    try:
        posthog.report_exception(exception, request)
    except Exception:
        # send(), not send_robust(): anything raising here would escape
        # handle_uncaught_exception and replace the 500 page with a traceback.
        logger.exception("Could not report an exception to PostHog")


class WebGatesConfig(AppConfig):
    """Django app config for web gates."""

    name = "ludamus.gates.web.django"
    label = "web_gates"

    def ready(self) -> None:
        # `{% load vite_tags %}` imports the module lazily, mid-request, which is
        # too late for that request's `request_started` to have reset the
        # per-request set. Import it here so the receiver is connected first.
        import_module(f"{self.name}.templatetags.vite_tags")
        got_request_exception.connect(
            report_request_exception, dispatch_uid="posthog.report_request_exception"
        )
