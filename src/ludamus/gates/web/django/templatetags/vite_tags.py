"""Request-scoped deduplication for component-owned Vite assets.

A component that renders more than once per page (two dropzones on the event
settings form) would otherwise emit one identical <script> tag per instance.
"""

from contextvars import ContextVar

from django import template
from django.core.signals import request_started
from django.utils.safestring import SafeString
from django_vite.templatetags.django_vite import vite_asset

register = template.Library()

RESET_DISPATCH_UID = "vite_tags.reset_emitted"
_emitted: ContextVar[set[str] | None] = ContextVar("vite_assets_emitted", default=None)


def reset_emitted_assets(**_kwargs: object) -> None:
    _emitted.set(set())


request_started.connect(reset_emitted_assets, dispatch_uid=RESET_DISPATCH_UID)


@register.simple_tag
def vite_asset_once(path: str) -> SafeString:
    """Render an asset's tags the first time a request asks for them.

    Returns:
        The asset's tags, or an empty string for a repeat within one request.
    """
    # Outside a request there is no page to dedupe within, and suppressing a
    # tag we cannot prove is already on the page would be the worse failure.
    if (emitted := _emitted.get()) is None:
        return SafeString(vite_asset(path))
    if path in emitted:
        return SafeString("")
    emitted.add(path)
    return SafeString(vite_asset(path))
