from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.contrib.staticfiles.storage import staticfiles_storage

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ludamus.pacts import EventDTO, PersonalDataFieldDTO, SessionFieldDTO


def is_event_published(event: EventDTO) -> bool:
    return (
        event.publication_time is not None
        and event.publication_time <= datetime.now(tz=UTC)
    )


def parse_dynamic_field_value(
    *, request: HttpRequest, field: PersonalDataFieldDTO | SessionFieldDTO, key: str
) -> str | list[str] | bool:
    if field.field_type == "checkbox":
        return request.POST.get(key) == "true"
    if field.is_multiple:
        return request.POST.getlist(key)
    value = request.POST.get(key, "")
    if field.allow_custom and not value:
        value = request.POST.get(f"{key}_custom", "")
    return value


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
