from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.panel import pagination_context, safe_next_url
from ludamus.pacts import NotFoundError
from ludamus.pacts.multiverse import Capability

if TYPE_CHECKING:
    from collections.abc import Callable


class ErrataPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        errata = self.request.services.errata.list_for_event(current_event.pk)
        pagination = pagination_context(self.request, errata)
        context["active_nav"] = "errata"
        context["errata"] = list(pagination["page_obj"].object_list)
        # The subtitle counts the whole backlog, not the page in front of you.
        context["pending_count"] = sum(
            erratum.acknowledged_by_name is None for erratum in errata
        )
        context.update(pagination)
        return TemplateResponse(self.request, "panel/errata.html", context)


def _posted_log_pks(request: EventPanelRequest) -> list[int]:
    # A tick marks a whole erratum, so one field carries every row of it —
    # comma-joined, because the two rows of a move travel together. int() is
    # the validation: str.isdigit() would let through superscripts and other
    # non-ASCII digits it then refuses.
    return [
        int(pk) for raw in request.POST.getlist("log_pk") for pk in raw.split(",") if pk
    ]


def _erratum_action(
    *, view: EventContextMixin, slug: str, write: Callable[[int], None]
) -> HttpResponse:
    """Scope the event, apply one errata flag, and return to the list."""
    _context, current_event = view.get_event_context(slug)
    if current_event is None:
        return redirect("panel:index")
    try:
        write(current_event.pk)
    except ValueError, NotFoundError:
        # A batch is all or nothing: a row of another event, or half a move,
        # refuses the whole post rather than quietly flagging the rest.
        return HttpResponse(status=HTTPStatus.UNPROCESSABLE_ENTITY)
    return redirect(
        safe_next_url(view.request, reverse("panel:errata", kwargs={"slug": slug}))
    )


class ErratumAcknowledgeActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    # The one write a comms member may perform.
    write_capability: ClassVar[Capability] = Capability.ERRATUM_ACK

    def post(self, request: EventPanelRequest, slug: str) -> HttpResponse:
        return _erratum_action(
            view=self,
            slug=slug,
            write=lambda event_pk: request.services.errata.set_acknowledged(
                event_pk=event_pk,
                log_pks=_posted_log_pks(request),
                user_id=request.context.current_user_id,
                acknowledged=request.POST.get("acknowledged") == "1",
            ),
        )


class ErratumImportantActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    # Flagging what to announce first is the same job as ticking off what was
    # announced, so it is the same capability.
    write_capability: ClassVar[Capability] = Capability.ERRATUM_ACK

    def post(self, request: EventPanelRequest, slug: str) -> HttpResponse:
        return _erratum_action(
            view=self,
            slug=slug,
            write=lambda event_pk: request.services.errata.set_important(
                event_pk=event_pk,
                log_pks=_posted_log_pks(request),
                important=request.POST.get("important") == "1",
            ),
        )
