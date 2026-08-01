# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
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

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    pagination_context,
    proposal_detail_tab_urls,
    proposal_tab_urls,
    safe_next_url,
)
from ludamus.gates.web.django.chronology.panel.views.columns import (
    PROPOSAL_COLUMNS,
    column_values,
    column_views,
)
from ludamus.pacts import NotFoundError, SessionStatus
from ludamus.pacts.chronology import (
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    ProposalScheduledError,
)
from ludamus.pacts.panel import SCHEDULED_FILTER, ProposalListQuery

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.pacts import FacilitatorDTO, OrganizerFieldDTO, SessionListItemDTO
    from ludamus.pacts.chronology import ProposalStatusServiceProtocol
    from ludamus.pacts.panel import PanelColumnDTO, ProposalPanelServiceProtocol

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


class ProposalsPageView(PanelAccessMixin, EventContextMixin, View):
    """List submitted proposals for an event."""

    request: PanelRequest

    def _read_query(
        self, track_pk: int | None, *, multi_tracks: bool
    ) -> ProposalListQuery:
        return ProposalListQuery(
            search=self.request.GET.get("search", "").strip(),
            category=self.request.GET.get("category", "").strip(),
            status=self.request.GET.get("status", ""),
            track_pk=track_pk,
            multi_tracks=multi_tracks,
            sort=self.request.GET.get("sort", "").strip(),
            raw_field_filters={
                int(key.removeprefix("field_")): self.request.GET.get(key, "")
                for key in self.request.GET
                if key.startswith("field_") and key.removeprefix("field_").isdigit()
            },
        )

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        sorted_tracks, managed_pks, filter_track_pk = self.get_track_filter_context(
            current_event.pk
        )
        filter_track_multi = self.request.GET.get("track") == "multi"
        query = self._read_query(filter_track_pk, multi_tracks=filter_track_multi)
        list_context = self.request.services.proposal_panel.list_context(
            event_id=current_event.pk, query=query
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
            self.request.services.proposal_panel.list_deleted(current_event.pk)
        )
        context["session_fields"] = list_context.filterable_fields
        context["filter_search"] = query.search
        context["filter_fields"] = {
            field.pk: query.raw_field_filters.get(field.pk, "")
            for field in list_context.filterable_fields
        }
        context["all_tracks"] = sorted_tracks
        context["managed_track_pks"] = managed_pks
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
        status_labels = {
            SessionStatus.PENDING: _("Pending"),
            SessionStatus.ACCEPTED: _("Accepted"),
            SessionStatus.ON_HOLD: _("On hold"),
            SessionStatus.REJECTED: _("Rejected"),
        }
        context["statuses"] = [
            *((str(s), status_labels[s]) for s in SessionStatus),
            (SCHEDULED_FILTER, _("Scheduled")),
        ]
        context["filter_status"] = list_context.status
        context["filter_sort"] = list_context.sort
        return TemplateResponse(self.request, "panel/proposals.html", context)


class ProposalDetailPageView(PanelAccessMixin, EventContextMixin, View):
    """View proposal details."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            session = self.request.services.proposal_panel.read_proposal(
                event_id=current_event.pk, proposal_id=proposal_id
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        field_values = self.request.di.uow.sessions.read_field_values(proposal_id)
        assigned_facilitators = self.request.di.uow.sessions.read_facilitators(
            proposal_id
        )
        preferred_time_slots = self.request.di.uow.sessions.read_preferred_time_slots(
            proposal_id
        )
        presenter = None
        if session.presenter_id is not None:
            presenter = self.request.di.uow.active_users.read_by_id(
                session.presenter_id
            )
        import_log_entry = self.request.services.import_log.log_entry_for_session(
            proposal_id
        )
        import_log_integration = None
        if import_log_entry is not None:
            try:
                import_log_integration = self.request.services.event_integrations.get(
                    current_event.pk, import_log_entry.integration_id
                )
            except NotFoundError:
                # Defensive: the linked integration doesn't belong to this
                # event (deleted, or stale link). Hide the back-link cleanly.
                import_log_entry = None

        category_name = None
        if session.category_id is not None:
            categories = self.request.di.uow.proposal_categories.list_by_event(
                current_event.pk
            )
            category_name = next(
                (c.name for c in categories if c.pk == session.category_id), None
            )

        track_ids = set(self.request.di.uow.sessions.read_track_ids(proposal_id))
        proposal_tracks = [
            t
            for t in self.request.di.uow.tracks.list_by_event(current_event.pk)
            if t.pk in track_ids
        ]

        agenda_item = self.request.di.uow.agenda_items.read_by_session(proposal_id)
        schedule_logs = self.request.di.uow.schedule_change_logs.list_by_session(
            proposal_id
        )

        context["active_nav"] = "proposals"
        context["active_tab"] = "details"
        context["tab_urls"] = proposal_detail_tab_urls(slug, proposal_id)
        context["proposal"] = session
        context["category_name"] = category_name
        context["proposal_tracks"] = proposal_tracks
        context["agenda_item"] = agenda_item
        context["schedule_logs"] = schedule_logs
        context["field_values"] = field_values
        context["facilitators"] = assigned_facilitators
        context["presenter"] = presenter
        context["preferred_time_slots"] = preferred_time_slots
        context["import_log_entry"] = import_log_entry
        context["import_log_integration"] = import_log_integration
        return TemplateResponse(self.request, "panel/proposal-detail.html", context)


class ProposalHistoryPageView(PanelAccessMixin, EventContextMixin, View):
    """Per-proposal change history tab."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.session_content_edit
        try:
            title, logs = service.session_history(
                event_id=current_event.pk, session_id=proposal_id
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
        context["field_names"] = service.list_field_names(current_event.pk)
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


class ProposalStatusActionView(PanelAccessMixin, EventContextMixin, View):
    """Shared POST handler for proposal status transitions."""

    request: PanelRequest
    http_method_names = ("post",)
    action = ""

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        apply_status = _status_transitions(self.request.services.proposal_status)[
            self.action
        ]
        try:
            apply_status(event_pk=current_event.pk, session_pk=proposal_id)
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)
        except ProposalScheduledError:
            messages.error(
                self.request,
                _(
                    "This session is scheduled and can only be accepted. "
                    "Remove it from the timetable to change its status."
                ),
            )
            return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)

        messages.success(self.request, _STATUS_MESSAGES[self.action])
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)


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


class ProposalBulkStatusActionView(PanelAccessMixin, EventContextMixin, View):
    """Apply one status transition to several proposals at once (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        back = safe_next_url(
            self.request, reverse("panel:proposals", kwargs={"slug": slug})
        )
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
                apply_status(event_pk=current_event.pk, session_pk=session_pk)
            except ProposalScheduledError:
                scheduled += 1
            except NotFoundError:
                missing += 1
            else:
                applied += 1

        self._report(applied=applied, scheduled=scheduled, missing=missing)
        return redirect(back)

    def _selected_pks(self) -> list[int]:
        pks = []
        for raw in self.request.POST.getlist("proposal_ids"):
            try:
                pks.append(int(raw))
            except ValueError:
                continue
        return pks

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


class ProposalDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            self.request.services.session_deletion.soft_delete(
                event_pk=current_event.pk,
                session_pk=proposal_id,
                user_pk=self.request.user.pk,
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        messages.success(self.request, _("Proposal deleted."))
        return redirect("panel:proposals", slug=slug)


class ProposalRestoreActionView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            self.request.services.session_deletion.restore(
                event_pk=current_event.pk, session_pk=proposal_id
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        messages.success(self.request, _("Proposal restored."))
        return redirect("panel:proposals", slug=slug)


class ProposalSetFacilitatorsActionView(PanelAccessMixin, EventContextMixin, View):
    """Set facilitators on a session (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            session = self.request.services.proposal_panel.read_proposal(
                event_id=current_event.pk, proposal_id=proposal_id
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        raw_ids = self.request.POST.getlist("facilitator_ids")
        submitted_ids = {int(fid) for fid in raw_ids if fid.isdigit()}
        all_facilitators = self.request.di.uow.facilitators.list_by_event(
            current_event.pk
        )
        valid_pks = {f.pk for f in all_facilitators}
        facilitator_ids = list(submitted_ids & valid_pks)
        self.request.di.uow.sessions.set_facilitators(session.pk, facilitator_ids)
        messages.success(self.request, _("Facilitators updated."))
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)


class ContentLogPageView(PanelAccessMixin, EventContextMixin, View):
    """Read-only activity log of session content edits for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "proposals"
        context["slug"] = slug
        service = self.request.services.session_content_edit
        logs = service.list_log(current_event.pk)
        context["logs"] = logs
        context["field_names"] = service.list_field_names(current_event.pk)
        context["revertible_pks"] = service.revertible_log_pks(current_event.pk, logs)
        facilitator_service = self.request.services.personal_data_field_values
        context["facilitator_logs"] = facilitator_service.list_log(current_event.pk)
        context["facilitator_field_names"] = facilitator_service.list_field_names(
            current_event.pk
        )
        return TemplateResponse(self.request, "panel/content-log.html", context)


class ContentLogRevertActionView(PanelAccessMixin, EventContextMixin, View):
    """Revert a logged session content change (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.session_content_edit
        try:
            service.revert(
                event_pk=current_event.pk, log_pk=pk, user_pk=self.request.user.pk
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
