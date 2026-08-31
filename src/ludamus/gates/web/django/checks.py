"""Startup checks for the web gates URLconf."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.checks import CheckMessage, Error
from django.urls import Resolver404, resolve
from django.views.static import serve

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps import AppConfig

MEDIA_URL_SHADOWED = "web_gates.E001"

_PROBE_FILE = "probe.png"


def check_media_url_reaches_serve(
    **_kwargs: Sequence[AppConfig] | Sequence[str] | None,
) -> list[CheckMessage]:
    """Report a local MEDIA_URL that an application route answers first."""
    if not settings.MEDIA_URL.startswith("/"):
        return []

    try:
        match = resolve(f"{settings.MEDIA_URL}{_PROBE_FILE}")
    except Resolver404:
        return []
    if match.func is serve:
        return []

    return [
        Error(
            f"MEDIA_URL {settings.MEDIA_URL!r} is answered by the "
            f"{match.view_name!r} route, so media files never reach the "
            f"media view.",
            hint="Move MEDIA_URL to a prefix no application route claims.",
            id=MEDIA_URL_SHADOWED,
        )
    ]
