import sys
from importlib import import_module
from typing import TYPE_CHECKING, Any

from django.apps import AppConfig
from django.core.signals import got_request_exception
from django.dispatch import receiver

from ludamus.gates.web.django import analytics

if TYPE_CHECKING:
    from django.http import HttpRequest


@receiver(got_request_exception)
def report_request_exception(*, request: HttpRequest, **_kwargs: Any) -> None:
    # Django converts a view exception into a response before it propagates
    # back through the middleware stack, so a middleware-based hook never sees
    # it. This signal does.
    exception = sys.exc_info()[1]
    if exception is not None:
        analytics.report_exception(exception, request)


class WebGatesConfig(AppConfig):
    """Django app config for web gates."""

    name = "ludamus.gates.web.django"
    label = "web_gates"

    def ready(self) -> None:
        # `{% load vite_tags %}` imports the module lazily, mid-request, which is
        # too late for that request's `request_started` to have reset the
        # per-request set. Import it here so the receiver is connected first.
        import_module(f"{self.name}.templatetags.vite_tags")
