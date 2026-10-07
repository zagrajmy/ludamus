"""Startup checks for the web gates URLconf."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core import checks
from django.core.checks import CheckMessage, Error
from django.urls import Resolver404, resolve
from django.views.static import serve

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps import AppConfig

MEDIA_URL_SHADOWED = "web_gates.E001"
POSTAL_ADDRESS_MISSING = "web_gates.W001"

_PROBE_FILE = "probe.png"


def check_media_url_reaches_serve(
    **_kwargs: Sequence[AppConfig] | Sequence[str] | None,
) -> list[CheckMessage]:
    """Report a local MEDIA_URL that an application route answers first."""
    if not settings.MEDIA_URL_IS_LOCAL:
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


def check_mail_postal_address(
    **_kwargs: Sequence[AppConfig] | Sequence[str] | None,
) -> list[CheckMessage]:
    """Warn when production sends opt-in email without a postal address."""
    if not settings.IS_PRODUCTION or settings.MAIL_POSTAL_ADDRESS:
        return []
    return [
        checks.Warning(
            "MAIL_POSTAL_ADDRESS is empty, so sphere announcement emails go "
            "out without the sender's postal address in their footer.",
            hint="Set MAIL_POSTAL_ADDRESS in the production environment.",
            id=POSTAL_ADDRESS_MISSING,
        )
    ]
