# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""Proposal/session list, detail, history, columns, and action views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    format_field_value,
    pagination_context,
    proposal_detail_tab_urls,
    proposal_tab_urls,
    safe_next_url,
)
from ludamus.pacts import NotFoundError, SessionStatus
from ludamus.pacts.chronology import (
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    ProposalScheduledError,
)
from ludamus.pacts.panel import (
    SCHEDULED_FILTER,
    EmptyColumnSelectionError,
    ProposalListQuery,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.pacts import FacilitatorDTO, PersonalDataFieldDTO, SessionListItemDTO
    from ludamus.pacts.panel import PanelColumnDTO, ProposalPanelServiceProtocol

    PersonalFieldItems = list[
        tuple[PersonalDataFieldDTO, str | list[str] | bool | None]
    ]
    FacilitatorPersonalData = list[tuple[FacilitatorDTO, str, PersonalFieldItems]]


def _builtin_cell(*, key: str, proposal: SessionListItemDTO) -> str:
    if key == "title":
        return proposal.title
    if key == "host":
        return proposal.display_name
    if key == "category":
        return proposal.category_name
    # "status" and "created" render richly in the template — a badge and a
    # localized date — so they carry no text cell.
    return ""


def _build_column_values(
    *,
    panel: ProposalPanelServiceProtocol,
    proposals: Sequence[SessionListItemDTO],
    columns: Sequence[PanelColumnDTO],
) -> dict[int, dict[str, str]]:
    raw_values = panel.column_values(
        session_ids=[p.pk for p in proposals],
        field_ids=[column.field.pk for column in columns if column.field is not None],
    )
    # One ready-to-render string per (proposal, column), so the template renders
    # every column the same way whatever the organizer chose.
    return {
        proposal.pk: {
            column.key: (
                format_field_value(
                    value=raw_values.get(proposal.pk, {}).get(column.field.slug)
                )
                if column.field is not None
                else _builtin_cell(key=column.key, proposal=proposal)
            )
            for column in columns
        }
        for proposal in proposals
    }


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
        column_values = _build_column_values(
            panel=self.request.services.proposal_panel,
            proposals=list(page_obj.object_list),
            columns=list_context.columns,
        )

        context["active_nav"] = "proposals"
        context["active_tab"] = "list"
        context["tab_urls"] = proposal_tab_urls(slug)
        context["columns"] = list_context.columns
        context["column_values"] = column_values
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


class ProposalColumnsPageView(PanelAccessMixin, EventContextMixin, View):
    """Choose which session fields show as columns on the proposals list."""

    request: PanelRequest

    def _render(
        self,
        *,
        context: dict[str, Any],
        slug: str,
        event_pk: int,
        error: str | None = None,
    ) -> HttpResponse:
        columns = self.request.services.proposal_panel.columns_context(event_pk)
        context["active_nav"] = "proposals"
        context["active_tab"] = "columns"
        context["tab_urls"] = proposal_tab_urls(slug)
        context["chosen_columns"] = columns.chosen
        context["available_columns"] = columns.available
        context["error"] = error
        return TemplateResponse(self.request, "panel/proposal-columns.html", context)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        return self._render(context=context, slug=slug, event_pk=current_event.pk)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        # The chosen keys arrive in display order; the service drops anything
        # that isn't this event's own column.
        try:
            self.request.services.proposal_panel.set_columns(
                event_id=current_event.pk, columns=self.request.POST.getlist("columns")
            )
        except EmptyColumnSelectionError:
            return self._render(
                context=context,
                slug=slug,
                event_pk=current_event.pk,
                error=_("Pick at least one column to show."),
            )

        messages.success(self.request, _("Columns updated."))
        return redirect("panel:proposals", slug=slug)


class ProposalDetailPageView(PanelAccessMixin, EventContextMixin, View):
    """View proposal details."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            session = self.request.di.uow.sessions.read(proposal_id)
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        session_event = self.request.di.uow.sessions.read_event(proposal_id)
        if session_event.pk != current_event.pk:
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


class ProposalStatusActionView(PanelAccessMixin, EventContextMixin, View):
    """Shared POST handler for proposal status transitions."""

    request: PanelRequest
    http_method_names = ("post",)
    success_message: str | _StrPromise = ""

    def _apply_status(self, *, event_pk: int, session_pk: int) -> None:
        raise NotImplementedError

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            self._apply_status(event_pk=current_event.pk, session_pk=proposal_id)
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

        messages.success(self.request, self.success_message)
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)


class ProposalPendingActionView(ProposalStatusActionView):
    """Move a proposal back to pending (POST only)."""

    success_message = gettext_lazy("Proposal moved back to pending.")

    def _apply_status(self, *, event_pk: int, session_pk: int) -> None:
        self.request.services.proposal_status.mark_pending(
            event_pk=event_pk, session_pk=session_pk
        )


class ProposalAcceptActionView(ProposalStatusActionView):
    """Mark a proposal accepted (POST only)."""

    success_message = gettext_lazy("Proposal accepted.")

    def _apply_status(self, *, event_pk: int, session_pk: int) -> None:
        self.request.services.proposal_status.mark_accepted(
            event_pk=event_pk, session_pk=session_pk
        )


class ProposalHoldActionView(ProposalStatusActionView):
    """Put a proposal on hold / reserve list (POST only)."""

    success_message = gettext_lazy("Proposal put on hold.")

    def _apply_status(self, *, event_pk: int, session_pk: int) -> None:
        self.request.services.proposal_status.mark_on_hold(
            event_pk=event_pk, session_pk=session_pk
        )


class ProposalRejectActionView(ProposalStatusActionView):
    """Reject a proposal (POST only)."""

    success_message = gettext_lazy("Proposal rejected.")

    def _apply_status(self, *, event_pk: int, session_pk: int) -> None:
        self.request.services.proposal_status.mark_rejected(
            event_pk=event_pk, session_pk=session_pk
        )


_BULK_STATUS_METHODS = {
    "pending": "mark_pending",
    "accept": "mark_accepted",
    "hold": "mark_on_hold",
    "reject": "mark_rejected",
}


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
        method_name = _BULK_STATUS_METHODS.get(self.request.POST.get("action", ""))
        if method_name is None:
            messages.error(self.request, _("Unknown bulk action."))
            return redirect(back)

        if not (session_pks := self._selected_pks()):
            messages.warning(self.request, _("No proposals selected."))
            return redirect(back)

        apply_status = getattr(self.request.services.proposal_status, method_name)
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
            session = self.request.di.uow.sessions.read(proposal_id)
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        session_event = self.request.di.uow.sessions.read_event(proposal_id)
        if session_event.pk != current_event.pk:
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
        context["logs"] = service.list_log(current_event.pk)
        context["field_names"] = service.list_field_names(current_event.pk)
        context["revertible_pks"] = service.revertible_log_pks(current_event.pk)
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
