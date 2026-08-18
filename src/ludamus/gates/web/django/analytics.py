from __future__ import annotations

import atexit
from functools import cache
from typing import TYPE_CHECKING

from django.conf import settings
from posthog import Posthog

if TYPE_CHECKING:
    from django.http import HttpRequest


@cache
def client() -> Posthog | None:
    """Build the PostHog client once, or None when analytics is unconfigured."""
    if not settings.POSTHOG_API_KEY:
        return None

    posthog = Posthog(
        project_api_key=settings.POSTHOG_API_KEY,
        host=settings.POSTHOG_HOST,
        # Faults are reported through report_exception() below, which keeps
        # them anonymous. Autocapture would bypass that, and it cannot see view
        # exceptions anyway — Django turns those into a response before they
        # reach any hook it installs.
        enable_exception_autocapture=False,
    )
    # Events queue on a background thread; without this the last batch dies
    # with the worker.
    atexit.register(posthog.shutdown)
    return posthog


def report_exception(exception: BaseException, request: HttpRequest) -> None:
    """Report a server-side fault, tagged with the user pk for debugging."""
    posthog = client()
    if posthog is None:
        return

    # The pk rides along as distinct_id so a report can be traced back to the
    # account that hit it. $process_person_profile stays False regardless:
    # consent lives in the browser's localStorage and the server cannot read
    # it, so a fault report has to be safe to send for someone who declined.
    # That combination makes the event searchable by pk without building a
    # person, accumulating properties, or starting a cross-event timeline.
    # disable_geoip keeps the ingestion IP from becoming location data.
    user = getattr(request, "user", None)
    identified = user is not None and user.is_authenticated
    posthog.capture_exception(
        exception,
        distinct_id=str(user.pk) if identified else "server",
        properties={"$process_person_profile": False, "path": request.path},
        disable_geoip=True,
    )
