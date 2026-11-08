"""The base of every event panel page: panel access, then the event it names."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, ClassVar

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.panel import PanelAccessMixin, PanelRequest, safe_next_url
from ludamus.gates.web.django.request_ids import parse_id
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.panel import FIELD_KEY_PREFIX
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.http import HttpRequest, HttpResponseBase

    from ludamus.pacts.event import EventDTO, EventPanelContextDTO
    from ludamus.pacts.tracks import TrackFilterDTO


type PanelContext = dict[str, object]


class _EventResolution(View):
    # Sits after the access mixins in the MRO, so their checks run first and
    # the event is read before any handler looks at the request.
    request: PanelRequest
    current_event: EventDTO
    event_slug_kwarg: ClassVar[str] = "slug"

    def dispatch(
        self, request: HttpRequest, *args: str, **kwargs: str | int
    ) -> HttpResponseBase:
        try:
            self.current_event = self.request.services.events.read_by_slug(
                self.request.context.current_sphere_id,
                str(kwargs[self.event_slug_kwarg]),
            )
        except NotFoundError:
            return self.event_not_found()
        return super().dispatch(request, *args, **kwargs)

    def event_not_found(self) -> HttpResponseBase:
        messages.error(self.request, _("Event not found."))
        return redirect("panel:index")


class EventPanelMixin(PanelAccessMixin, _EventResolution):
    """A panel page about the event its URL names.

    The event is read once per request, before the handler runs; a slug this
    sphere has no event for sends the organizer back to the panel index. The
    sidebar's event list and counters cost queries of their own, so only a
    page that renders the panel chrome asks for them through
    `panel_context()`.
    """

    request: PanelRequest

    @cached_property
    def _panel_page(self) -> EventPanelContextDTO:
        return self.request.services.event_panel.load_context(
            sphere_id=self.request.context.current_sphere_id,
            current_event=self.current_event,
        )

    def panel_context(self) -> PanelContext:
        # A fresh dict on every call: views fill it in place.
        page = self._panel_page
        return {
            "events": page.events,
            "current_event": page.current_event,
            "is_proposal_active": page.is_proposal_active,
            "stats": page.stats.model_dump(),
        }


def read_track_filter(request: PanelRequest, event_pk: int) -> TrackFilterDTO:
    """Read the `?track=` switcher state; a track of another event is a 404."""
    try:
        return request.services.tracks_panel.track_filter(
            event_pk=event_pk,
            manager_id=request.context.current_user_id,
            requested_pk=parse_id(request.GET.get("track")),
            auto_select="track" not in request.GET,
        )
    except NotFoundError:
        raise Http404 from None


def back_to_proposals(request: HttpRequest, slug: str) -> str:
    return safe_next_url(request, reverse("panel:proposals", kwargs={"slug": slug}))


def proposal_detail_url(*, request: HttpRequest, slug: str, proposal_id: int) -> str:
    # A bare proposals URL means the pending backlog, so the detail page has to
    # keep carrying the query the organizer arrived with.
    detail = reverse(
        "panel:proposal-detail", kwargs={"slug": slug, "proposal_id": proposal_id}
    )
    back = safe_next_url(request, "")
    return f"{detail}?{urlencode({'next': back})}" if back else detail


def format_field_value(
    *, value: str | list[str] | bool | None, labels: Mapping[str, str] | None = None
) -> str:
    # A stored answer holds option *values*; pass `labels` where the reader
    # should see the option labels instead, and a checkbox as a word rather
    # than "True".
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    by_value = labels or {}
    if isinstance(value, list):
        return ", ".join(by_value.get(item) or item for item in value)
    return by_value.get(value or "") or value or ""


def read_field_filters(request: HttpRequest) -> dict[int, str]:
    # `?field_<pk>=value`, one entry per configurable column the organizer
    # narrowed by. The pk is the mill's to resolve — a field this event does
    # not have drops out there, not here.
    return {
        pk: request.GET.get(key, "")
        for key in request.GET
        if key.startswith(FIELD_KEY_PREFIX)
        and (pk := parse_id(key.removeprefix(FIELD_KEY_PREFIX))) is not None
    }


def read_accreditation_filter(request: HttpRequest) -> str:
    # A tampered value falls back to "all", so no toolbar ever shows a selected
    # option the list is not actually filtered by. The options beside it are
    # `ACCREDITATION_TYPE_CHOICES` — the list the form already renders.
    raw = request.GET.get("accreditation", "").strip()
    return raw if raw in AccreditationType else ""
