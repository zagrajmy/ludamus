from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import Http404

from ludamus.gates.web.django.access import panel_access
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO


def is_event_published(event: EventDTO) -> bool:
    return (
        event.publication_time is not None
        and event.publication_time <= datetime.now(tz=UTC)
    )


def read_public_event(request: RootRequest, slug: str) -> EventDTO:
    # The event as a public page sees it: absent until published, except to
    # someone who manages the sphere and previews it.
    try:
        event = request.services.events.read_by_slug(
            request.context.current_sphere_id, slug
        )
    except NotFoundError as exc:
        raise Http404 from exc
    if not is_event_published(event) and not panel_access(request).granted:
        raise Http404
    return event


def get_client_ip(request: HttpRequest) -> str:
    if forwarded := request.META.get("HTTP_X_FORWARDED_FOR", ""):
        # The rightmost entry is appended by our own reverse proxy;
        # everything left of it is client-supplied and spoofable.
        return str(forwarded).rsplit(",", maxsplit=1)[-1].strip()
    return str(request.META.get("REMOTE_ADDR", ""))


PLACEHOLDER_COVER_IMAGES = (
    "placeholder-images/01.webp",  # meeples
    "placeholder-images/02.webp",  # chess
    "placeholder-images/03.webp",  # cards
    "placeholder-images/04.webp",  # dice
    "placeholder-images/05.webp",  # tabletop
    "placeholder-images/06.webp",  # chess pieces
    "placeholder-images/07.webp",  # board game
    "placeholder-images/08.webp",  # retro arcade
    "placeholder-images/09.webp",  # controller
    "placeholder-images/10.webp",  # arcade
)


def placeholder_cover_url(key: int) -> str:
    # Deterministic so a given event/session keeps the same placeholder.
    name = PLACEHOLDER_COVER_IMAGES[key % len(PLACEHOLDER_COVER_IMAGES)]
    return staticfiles_storage.url(name)
