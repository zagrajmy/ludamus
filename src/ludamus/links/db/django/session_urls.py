"""Absolute links to one session, for mail and cross-sphere pages."""

from __future__ import annotations

from django.urls import reverse

from ludamus.links.absolute_url import absolute_url


def session_popup_url(*, event_slug: str, session_id: int, domain: str) -> str:
    # NOTE: the event page's script opens the popup from ?session=.
    path = reverse("web:chronology:event", kwargs={"slug": event_slug})
    return f"{absolute_url(path, domain=domain)}?session={session_id}"
