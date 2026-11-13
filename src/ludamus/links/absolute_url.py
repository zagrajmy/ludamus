"""Absolute links out of a sphere's own domain.

Spheres live on separate sites, so anything that leaves one — a notification,
a cross-sphere dashboard row — has to name the host explicitly. Django's
``reverse`` only ever yields a path.
"""

from __future__ import annotations

from django.urls import reverse


def absolute_url(path: str, *, domain: str) -> str:
    scheme = "http" if "localhost" in domain else "https"
    return f"{scheme}://{domain}{path}"


def session_popup_url(*, event_slug: str, session_id: int, domain: str) -> str:
    # NOTE: the event page's script opens the popup from ?session=.
    path = reverse("web:chronology:event", kwargs={"slug": event_slug})
    return f"{absolute_url(path, domain=domain)}?session={session_id}"
