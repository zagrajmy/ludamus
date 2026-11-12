"""Proposal/session list, detail, history, columns, and action views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelMixin,
    back_to_proposals,
    proposal_detail_url,
    read_field_filters,
    read_track_filter,
)
from ludamus.gates.web.django.event.panel.views.columns import (
    PROPOSAL_COLUMNS,
    column_values,
    column_views,
)
from ludamus.gates.web.django.pagination import pagination_context
from ludamus.gates.web.django.panel import (
    PROPOSAL_STATUS_LABELS,
    SCHEDULED_LABEL,
    PanelRequest,
    proposal_detail_tab_urls,
    proposal_tab_urls,
)
from ludamus.gates.web.django.request_ids import parse_id, parse_ids
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.panel import SCHEDULED_FILTER, STATUS_ALL, ProposalListQuery
from ludamus.pacts.sessions import (
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    ProposalScheduledError,
    SessionStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.http import HttpRequest, HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.pacts.facilitators import FacilitatorDTO
    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.panel import PanelColumnDTO, ProposalPanelServiceProtocol
    from ludamus.pacts.sessions import ProposalStatusServiceProtocol, SessionListItemDTO

    PersonalFieldItems = list[tuple[OrganizerFieldDTO, str | list[str] | bool | None]]
    FacilitatorPersonalData = list[tuple[FacilitatorDTO, str, PersonalFieldItems]]


def _build_column_values(
    *,
    panel: ProposalPanelServiceProtocol,
    proposals: Sequence[SessionListItemDTO],
    columns: Sequence[PanelColumnDTO],
) -> dict[int, dict[str, str]]:
    return column_values(
        rows=proposals,
        columns=columns,
        builtins=PROPOSAL_COLUMNS,
        raw_values=panel.column_values(
            session_ids=[p.pk for p in proposals],
            field_ids=[c.field.pk for c in columns if c.field is not None],
        ),
    )


def read_proposal_query(
    request: HttpRequest, *, track_pk: int | None
) -> ProposalListQuery:
    # The one reader of the list's filters: the list and its export both go
    # through here, so a filter cannot apply to one and not the other.
    return ProposalListQuery(
        search=request.GET.get("search", "").strip(),
        category_pk=parse_id(request.GET.get("category")),
        # Default (no status param) is the pending backlog — the queue an
        # organizer opens this page to work through. STATUS_ALL (or any
        # other unknown value) still shows everything.
        status=request.GET.get("status", SessionStatus.PENDING.value),
        track_pk=track_pk,
        multi_tracks=request.GET.get("track") == "multi",
        sort=request.GET.get("sort", "").strip(),
        raw_field_filters=read_field_filters(request),
    )


class ProposalsPageView(EventPanelMixin, View):
    """List submitted proposals for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        tracks = read_track_filter(self.request, self.current_event.pk)
        filter_track_pk = tracks.selected_pk
        query = read_proposal_query(self.request, track_pk=filter_track_pk)
        filter_track_multi = query.multi_tracks
        list_context = self.request.services.proposal_panel.list_context(
            event_id=self.current_event.pk, query=query
        )
        pagination = pagination_context(self.request, list_context.proposals)
        page_obj = pagination["page_obj"]
        cells = _build_column_values(
            panel=self.request.services.proposal_panel,
            proposals=list(page_obj.object_list),
            columns=list_context.columns,
        )

        context["active_nav"] = "proposals"
        context["active_tab"] = "list"
        context["tab_urls"] = proposal_tab_urls(slug)
        context["columns"] = column_views(list_context.columns, PROPOSAL_COLUMNS)
        context["column_values"] = cells
        context["proposals"] = list(page_obj.object_list)
        context.update(pagination)
        context["deleted_proposals"] = (
            self.request.services.proposal_panel.list_deleted(self.current_event.pk)
        )
        context["session_fields"] = list_context.filterable_fields
        context["filter_search"] = query.search
        context["filter_fields"] = {
            field.pk: query.raw_field_filters.get(field.pk, "")
            for field in list_context.filterable_fields
        }
        context["all_tracks"] = tracks.tracks
        context["managed_track_pks"] = tracks.managed_pks
        context["filter_track_pk"] = filter_track_pk
        context["filter_track_multi"] = filter_track_multi
        # Value the other filter form echoes back so the track selection
        # round-trips. Empty string ("All tracks") must stay present in the
        # query, or the absent-param default re-selects the managed track.
        context["filter_track_value"] = (
            "multi"
            if filter_track_multi
            else str(filter_track_pk) if filter_track_pk is not None else ""
        )
        context["categories"] = list_context.categories
        context["filter_category_pk"] = list_context.category_pk
        context["statuses"] = [
            *((str(s), str(PROPOSAL_STATUS_LABELS[s])) for s in SessionStatus),
            (SCHEDULED_FILTER, str(SCHEDULED_LABEL)),
        ]
        context["filter_status"] = list_context.status
        # Value the track form and the Clear link echo back so the status
        # selection round-trips. "All statuses" must stay present in the query,
        # or the absent-param default re-selects the pending backlog.
        context["filter_status_value"] = list_context.status or STATUS_ALL
        context["filter_sort"] = list_context.sort
        return TemplateResponse(self.request, "panel/proposals.html", context)


class ProposalDetailPageView(EventPanelMixin, View):
    """View proposal details."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        context = self.panel_context()

        try:
            detail = self.request.services.proposal_page.detail(
                event_id=self.current_event.pk, proposal_id=proposal_id
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        import_log_entry = self.request.services.import_log.log_entry_for_session(
            proposal_id
        )
        import_log_integration = None
        if import_log_entry is not None:
            try:
                import_log_integration = self.request.services.event_integrations.get(
                    self.current_event.pk, import_log_entry.integration_id
                )
            except NotFoundError:
                # Defensive: the linked integration doesn't belong to this
                # event (deleted, or stale link). Hide the back-link cleanly.
                import_log_entry = None

        context["active_nav"] = "proposals"
        context["active_tab"] = "details"
        context["tab_urls"] = proposal_detail_tab_urls(slug, proposal_id)
        context["proposal"] = detail.proposal
        context["category_name"] = detail.category_name
        context["proposal_tracks"] = detail.tracks
        context["agenda_item"] = detail.schedule.agenda_item
        context["schedule_logs"] = detail.schedule.logs
        context["field_values"] = detail.field_values
        context["facilitators"] = detail.facilitators
        context["presenter"] = detail.presenter
        context["availability"] = detail.schedule.availability
        context["import_log_entry"] = import_log_entry
        context["import_log_integration"] = import_log_integration
        # Carries the list's filters back: the breadcrumb and the action forms
        # both return here, and a bare proposals URL means the pending backlog.
        context["back_url"] = back_to_proposals(self.request, slug)
        return TemplateResponse(self.request, "panel/proposal-detail.html", context)


class ProposalHistoryPageView(EventPanelMixin, View):
    """Per-proposal change history tab."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        context = self.panel_context()

        service = self.request.services.session_content_edit
        try:
            title, logs = service.session_history(
                event_id=self.current_event.pk, session_id=proposal_id
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        context["active_nav"] = "proposals"
        context["active_tab"] = "history"
        context["tab_urls"] = proposal_detail_tab_urls(slug, proposal_id)
        context["item_name"] = title
        context["back_url"] = reverse("panel:proposals", kwargs={"slug": slug})
        context["back_label"] = _("Proposals")
        context["logs"] = logs
        context["field_names"] = service.list_field_names(self.current_event.pk)
        return TemplateResponse(self.request, "panel/item-history.html", context)


class _StatusTransition(Protocol):
    """One of the status service's `mark_*` methods."""

    def __call__(self, *, event_pk: int, session_pk: int) -> None: ...


def _status_transitions(
    service: ProposalStatusServiceProtocol,
) -> dict[str, _StatusTransition]:
    # Spelled out rather than resolved by name: the type checker sees every
    # call, and grepping for a transition finds this table. One table serves
    # both the single-proposal views and the bulk one.
    return {
        "pending": service.mark_pending,
        "accept": service.mark_accepted,
        "hold": service.mark_on_hold,
        "reject": service.mark_rejected,
    }


_STATUS_MESSAGES: dict[str, _StrPromise] = {
    "pending": gettext_lazy("Proposal moved back to pending."),
    "accept": gettext_lazy("Proposal accepted."),
    "hold": gettext_lazy("Proposal put on hold."),
    "reject": gettext_lazy("Proposal rejected."),
}


class ProposalStatusActionView(EventPanelMixin, View):
    """Shared POST handler for proposal status transitions."""

    request: PanelRequest
    http_method_names = ("post",)
    action = ""

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        apply_status = _status_transitions(self.request.services.proposal_status)[
            self.action
        ]
        detail_url = proposal_detail_url(
            request=self.request, slug=slug, proposal_id=proposal_id
        )
        try:
            apply_status(event_pk=self.current_event.pk, session_pk=proposal_id)
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect(back_to_proposals(self.request, slug))
        except ProposalScheduledError:
            messages.error(
                self.request,
                _(
                    "This session is scheduled and can only be accepted. "
                    "Remove it from the timetable to change its status."
                ),
            )
            return redirect(detail_url)

        messages.success(self.request, _STATUS_MESSAGES[self.action])
        return redirect(detail_url)


class ProposalPendingActionView(ProposalStatusActionView):
    """Move a proposal back to pending (POST only)."""

    action = "pending"


class ProposalAcceptActionView(ProposalStatusActionView):
    """Mark a proposal accepted (POST only)."""

    action = "accept"


class ProposalHoldActionView(ProposalStatusActionView):
    """Put a proposal on hold / reserve list (POST only)."""

    action = "hold"


class ProposalRejectActionView(ProposalStatusActionView):
    """Reject a proposal (POST only)."""

    action = "reject"


class ProposalBulkStatusActionView(EventPanelMixin, View):
    """Apply one status transition to several proposals at once (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        back = back_to_proposals(self.request, slug)
        transitions = _status_transitions(self.request.services.proposal_status)
        apply_status = transitions.get(self.request.POST.get("action", ""))
        if apply_status is None:
            messages.error(self.request, _("Unknown bulk action."))
            return redirect(back)

        if not (session_pks := self._selected_pks()):
            messages.warning(self.request, _("No proposals selected."))
            return redirect(back)

        applied = scheduled = missing = 0
        for session_pk in session_pks:
            try:
                apply_status(event_pk=self.current_event.pk, session_pk=session_pk)
            except ProposalScheduledError:
                scheduled += 1
            except NotFoundError:
                missing += 1
            else:
                applied += 1

        self._report(applied=applied, scheduled=scheduled, missing=missing)
        return redirect(back)

    def _selected_pks(self) -> list[int]:
        return parse_ids(self.request.POST.getlist("proposal_ids"))

    def _report(self, *, applied: int, scheduled: int, missing: int) -> None:
        if applied:
            messages.success(
                self.request,
                ngettext(
                    "%(count)d proposal updated.",
                    "%(count)d proposals updated.",
                    applied,
                )
                % {"count": applied},
            )
        if scheduled:
            messages.warning(
                self.request,
                ngettext(
                    "%(count)d scheduled proposal was skipped; remove it from "
                    "the timetable to change its status.",
                    "%(count)d scheduled proposals were skipped; remove them "
                    "from the timetable to change their status.",
                    scheduled,
                )
                % {"count": scheduled},
            )
        if missing:
            messages.error(
                self.request,
                ngettext(
                    "%(count)d proposal could not be found.",
                    "%(count)d proposals could not be found.",
                    missing,
                )
                % {"count": missing},
            )


class ProposalDeleteActionView(EventPanelMixin, View):
    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        back = back_to_proposals(self.request, slug)
        try:
            self.request.services.session_deletion.soft_delete(
                event_pk=self.current_event.pk,
                session_pk=proposal_id,
                user_pk=self.request.user.pk,
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect(back)

        messages.success(self.request, _("Proposal deleted."))
        return redirect(back)


class ProposalRestoreActionView(EventPanelMixin, View):
    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        back = back_to_proposals(self.request, slug)
        try:
            self.request.services.session_deletion.restore(
                event_pk=self.current_event.pk, session_pk=proposal_id
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect(back)

        messages.success(self.request, _("Proposal restored."))
        return redirect(back)


class ProposalSetFacilitatorsActionView(EventPanelMixin, View):
    """Set facilitators on a session (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        try:
            self.request.services.proposal_page.set_facilitators(
                event_id=self.current_event.pk,
                proposal_id=proposal_id,
                facilitator_ids=parse_ids(self.request.POST.getlist("facilitator_ids")),
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        messages.success(self.request, _("Facilitators updated."))
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)


class ContentLogPageView(EventPanelMixin, View):
    """Read-only activity log of session content edits for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        context["active_nav"] = "proposals"
        context["slug"] = slug
        service = self.request.services.session_content_edit
        logs = service.list_log(self.current_event.pk)
        context["logs"] = logs
        context["field_names"] = service.list_field_names(self.current_event.pk)
        context["revertible_pks"] = service.revertible_log_pks(
            self.current_event.pk, logs
        )
        facilitator_service = self.request.services.personal_data_field_values
        context["facilitator_logs"] = facilitator_service.list_log(
            self.current_event.pk
        )
        context["facilitator_field_names"] = facilitator_service.list_field_names(
            self.current_event.pk
        )
        return TemplateResponse(self.request, "panel/content-log.html", context)


class ContentLogRevertActionView(EventPanelMixin, View):
    """Revert a logged session content change (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        service = self.request.services.session_content_edit
        try:
            service.revert(
                event_pk=self.current_event.pk, log_pk=pk, user_pk=self.request.user.pk
            )
        except NotFoundError:
            messages.error(self.request, _("Change not found."))
        except ContentChangeNotLatestError:
            messages.error(
                self.request, _("Only the latest change for a session can be reverted.")
            )
        except ContentChangeNotRevertibleError:
            messages.error(
                self.request,
                _(
                    "This change cannot be reverted: cover image and assignment "
                    "changes are not restorable."
                ),
            )
        else:
            messages.success(self.request, _("Change reverted."))
        return redirect("panel:content-log", slug=slug)
