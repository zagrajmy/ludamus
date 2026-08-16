from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.multiverse import Capability


class ErrataPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        errata = self.request.services.errata.list_for_event(current_event.pk)
        context["active_nav"] = "errata"
        context["errata"] = errata
        context["pending_count"] = sum(
            erratum.acknowledged_by_name is None for erratum in errata
        )
        return TemplateResponse(self.request, "panel/errata.html", context)


class ErratumAcknowledgeActionView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest
    # The one write a comms member may perform.
    write_capability: ClassVar[Capability] = Capability.ERRATUM_ACK

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        raw_pks = request.POST.getlist("log_pk")
        if not raw_pks or not all(pk.isdigit() for pk in raw_pks):
            return HttpResponse(status=HTTPStatus.UNPROCESSABLE_ENTITY)
        try:
            request.services.errata.set_acknowledged(
                event_pk=current_event.pk,
                log_pks=[int(pk) for pk in raw_pks],
                user_id=request.context.current_user_id,
                acknowledged=request.POST.get("acknowledged") == "1",
            )
        except NotFoundError:
            return HttpResponse(status=HTTPStatus.UNPROCESSABLE_ENTITY)
        return redirect("panel:errata", slug=slug)
