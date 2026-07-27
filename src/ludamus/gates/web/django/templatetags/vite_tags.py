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

_emitted: ContextVar[set[str]] = ContextVar("vite_assets_emitted")


def _reset_emitted(**_kwargs: object) -> None:
    _emitted.set(set())


request_started.connect(_reset_emitted, dispatch_uid="vite_tags.reset_emitted")


@register.simple_tag
def vite_asset_once(path: str) -> SafeString:
    """Render an asset's tags the first time it is asked for in a request.

    Returns:
        The asset's tags, or an empty string if they were already emitted.
    """
    try:
        emitted = _emitted.get()
    except LookupError:
        emitted = set()
        _emitted.set(emitted)
    if path in emitted:
        return SafeString("")
    emitted.add(path)
    return SafeString(vite_asset(path))
