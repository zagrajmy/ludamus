from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import pagination_context
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.panel import safe_next_url
from ludamus.pacts import NotFoundError
from ludamus.pacts.multiverse import Capability


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
    # A checkbox ticks off a whole erratum, so one field may carry the two rows
    # of a move. int() is the validation: str.isdigit() would let through
    # superscripts and other non-ASCII digits it then refuses.
    return [
        int(pk) for raw in request.POST.getlist("log_pk") for pk in raw.split(",") if pk
    ]


class ErratumAcknowledgeActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    # The one write a comms member may perform.
    write_capability: ClassVar[Capability] = Capability.ERRATUM_ACK

    def post(self, request: EventPanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            request.services.errata.set_acknowledged(
                event_pk=current_event.pk,
                log_pks=_posted_log_pks(request),
                user_id=request.context.current_user_id,
                acknowledged=request.POST.get("acknowledged") == "1",
            )
        except ValueError, NotFoundError:
            return HttpResponse(status=HTTPStatus.UNPROCESSABLE_ENTITY)
        return redirect(
            safe_next_url(request, reverse("panel:errata", kwargs={"slug": slug}))
        )


class ErratumImportantActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    # Flagging what to announce first is the same job as ticking off what was
    # announced, so it is the same capability.
    write_capability: ClassVar[Capability] = Capability.ERRATUM_ACK

    def post(self, request: EventPanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            request.services.errata.set_important(
                event_pk=current_event.pk,
                log_pks=_posted_log_pks(request),
                important=request.POST.get("important") == "1",
            )
        except ValueError, NotFoundError:
            return HttpResponse(status=HTTPStatus.UNPROCESSABLE_ENTITY)
        return redirect(
            safe_next_url(request, reverse("panel:errata", kwargs={"slug": slug}))
        )
