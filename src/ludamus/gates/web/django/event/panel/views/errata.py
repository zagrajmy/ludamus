from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.gates.web.django.pagination import pagination_context
from ludamus.gates.web.django.panel import PanelRequest, safe_next_url
from ludamus.gates.web.django.request_ids import parse_ids
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.sphere import Capability

if TYPE_CHECKING:
    from collections.abc import Callable


class ErrataPageView(EventPanelMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        context = self.panel_context()
        errata = self.request.services.errata.list_for_event(self.current_event.pk)
        pagination = pagination_context(self.request, errata)
        context["active_nav"] = "errata"
        context["errata"] = list(pagination["page_obj"].object_list)
        # The subtitle counts the whole backlog, not the page in front of you.
        context["pending_count"] = sum(
            erratum.acknowledged_by_name is None for erratum in errata
        )
        context.update(pagination)
        return TemplateResponse(self.request, "panel/errata.html", context)


def _posted_log_pks(request: PanelRequest) -> list[int]:
    # A tick marks a whole erratum, so one field carries every row of it —
    # comma-joined, because the two rows of a move travel together.
    raws = [pk for raw in request.POST.getlist("log_pk") for pk in raw.split(",") if pk]
    if len(pks := parse_ids(raws)) != len(raws):
        raise ValueError
    return pks


def _erratum_action(
    *, view: EventPanelMixin, slug: str, write: Callable[[int], None]
) -> HttpResponse:
    """Scope the event, apply one errata flag, and return to the list."""
    try:
        write(view.current_event.pk)
    except ValueError, NotFoundError:
        # A batch is all or nothing: a row of another event, or half a move,
        # refuses the whole post rather than quietly flagging the rest.
        return HttpResponse(status=HTTPStatus.UNPROCESSABLE_ENTITY)
    return redirect(
        safe_next_url(view.request, reverse("panel:errata", kwargs={"slug": slug}))
    )


class ErratumAcknowledgeActionView(EventPanelMixin, View):
    request: PanelRequest
    # The one write a comms member may perform.
    write_capability: ClassVar[Capability] = Capability.ERRATUM_ACK

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
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


class ErratumImportantActionView(EventPanelMixin, View):
    request: PanelRequest
    # Flagging what to announce first is the same job as ticking off what was
    # announced, so it is the same capability.
    write_capability: ClassVar[Capability] = Capability.ERRATUM_ACK

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
        return _erratum_action(
            view=self,
            slug=slug,
            write=lambda event_pk: request.services.errata.set_important(
                event_pk=event_pk,
                log_pks=_posted_log_pks(request),
                important=request.POST.get("important") == "1",
            ),
        )
