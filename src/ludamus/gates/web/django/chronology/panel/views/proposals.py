# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""Proposal/session list, detail, edit, create, and action views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    make_unique_slug,
)
from ludamus.gates.web.django.forms import SessionEditForm, create_proposal_form
from ludamus.pacts import (
    NotFoundError,
    SessionData,
    SessionFieldValueData,
    SessionStatus,
    SessionUpdateData,
)
from ludamus.pacts.legacy import resolve_cover_image

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts import EventDTO, FacilitatorListItemDTO, SessionFieldDTO


class ProposalsPageView(PanelAccessMixin, EventContextMixin, View):
    """List submitted proposals for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "proposals"

        search = self.request.GET.get("search", "").strip() or None
        session_fields = self.request.di.uow.session_fields.list_by_event(
            current_event.pk
        )
        filterable_fields = [f for f in session_fields if f.field_type == "select"]
        field_filters: dict[int, str] = {}
        for field in filterable_fields:
            if value := self.request.GET.get(f"field_{field.pk}", "").strip():
                field_filters[field.pk] = value

        sorted_tracks, managed_pks, filter_track_pk = self.get_track_filter_context(
            current_event.pk
        )

        context["proposals"] = self.request.di.uow.sessions.list_sessions_by_event(
            current_event.pk,
            field_filters=field_filters or None,
            search=search,
            track_pk=filter_track_pk,
        )
        context["session_fields"] = filterable_fields
        context["filter_search"] = search or ""
        context["filter_fields"] = {
            field.pk: self.request.GET.get(f"field_{field.pk}", "")
            for field in filterable_fields
        }
        context["all_tracks"] = sorted_tracks
        context["managed_track_pks"] = managed_pks
        context["filter_track_pk"] = filter_track_pk
        return TemplateResponse(self.request, "panel/proposals.html", context)


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
        presenter = None
        if session.presenter_id is not None:
            presenter = self.request.di.uow.active_users.read_by_id(
                session.presenter_id
            )

        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["field_values"] = field_values
        context["facilitators"] = assigned_facilitators
        context["presenter"] = presenter
        return TemplateResponse(self.request, "panel/proposal-detail.html", context)


class ProposalEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit session fields for a proposal."""

    request: PanelRequest

    def _get_facilitator_context(
        self, event_pk: int, proposal_id: int
    ) -> tuple[list[FacilitatorListItemDTO], set[int]]:
        all_facilitators = self.request.di.uow.facilitators.list_by_event(event_pk)
        assigned = self.request.di.uow.sessions.read_facilitators(proposal_id)
        assigned_pks = {f.pk for f in assigned}
        return all_facilitators, assigned_pks

    def _update_facilitators(self, session_pk: int, event_pk: int) -> None:
        raw_ids = self.request.POST.getlist("facilitator_ids")
        submitted_ids = {int(fid) for fid in raw_ids if fid.isdigit()}
        all_facilitators = self.request.di.uow.facilitators.list_by_event(event_pk)
        valid_pks = {f.pk for f in all_facilitators}
        self.request.di.uow.sessions.set_facilitators(
            session_pk, list(submitted_ids & valid_pks)
        )

    def _save_session_fields(self, session_pk: int, event_pk: int) -> None:
        event_fields = self.request.di.uow.session_fields.list_by_event(event_pk)
        field_entries: list[SessionFieldValueData] = []
        for field in event_fields:
            key = f"session_field_{field.slug}"
            if field.field_type == "checkbox":
                value: str | list[str] | bool = self.request.POST.get(key) == "true"
            elif field.is_multiple:
                value = self.request.POST.getlist(key)
            else:
                value = self.request.POST.get(key, "")
                if field.allow_custom and not value:
                    value = self.request.POST.get(f"{key}_custom", "")
            field_entries.append(
                SessionFieldValueData(
                    session_id=session_pk, field_id=field.pk, value=value
                )
            )
        if field_entries:
            self.request.di.uow.sessions.save_field_values(session_pk, field_entries)

    def _get_session_fields(
        self, event_pk: int, proposal_id: int
    ) -> list[tuple[SessionFieldDTO, str | list[str] | bool | None]]:
        fields = self.request.di.uow.session_fields.list_by_event(event_pk)
        existing = self.request.di.uow.sessions.read_field_values(proposal_id)
        values_by_slug = {fv.field_slug: fv.value for fv in existing}
        return [(field, values_by_slug.get(field.slug)) for field in fields]

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

        all_facilitators, assigned_pks = self._get_facilitator_context(
            current_event.pk, proposal_id
        )
        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["form"] = SessionEditForm(
            initial={
                "title": session.title,
                "display_name": session.display_name,
                "description": session.description,
                "requirements": session.requirements,
                "needs": session.needs,
                "contact_email": session.contact_email,
                "participants_limit": session.participants_limit,
                "min_age": session.min_age,
                "duration": session.duration,
                "cover_image": session.cover_image_url or None,
            }
        )
        session_fields = self._get_session_fields(current_event.pk, proposal_id)
        context["all_facilitators"] = all_facilitators
        context["assigned_facilitator_pks"] = assigned_pks
        context["session_fields"] = session_fields
        return TemplateResponse(self.request, "panel/proposal-edit.html", context)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
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

        form = SessionEditForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            all_facilitators, assigned_pks = self._get_facilitator_context(
                current_event.pk, proposal_id
            )
            session_fields = self._get_session_fields(current_event.pk, proposal_id)
            context["active_nav"] = "proposals"
            context["proposal"] = session
            context["form"] = form
            context["all_facilitators"] = all_facilitators
            context["assigned_facilitator_pks"] = assigned_pks
            context["session_fields"] = session_fields
            return TemplateResponse(self.request, "panel/proposal-edit.html", context)

        update_data: SessionUpdateData = {
            "title": form.cleaned_data["title"],
            "display_name": form.cleaned_data["display_name"],
            "description": form.cleaned_data.get("description") or "",
            "requirements": form.cleaned_data.get("requirements") or "",
            "needs": form.cleaned_data.get("needs") or "",
            "contact_email": form.cleaned_data.get("contact_email") or "",
            "participants_limit": form.cleaned_data.get("participants_limit") or 0,
            "min_age": form.cleaned_data.get("min_age") or 0,
            "duration": form.cleaned_data.get("duration") or "",
        }
        cover = resolve_cover_image(form.cleaned_data.get("cover_image"))
        if cover is not None:
            update_data["cover_image"] = cover
        self.request.di.uow.sessions.update(proposal_id, update_data)

        self._update_facilitators(session.pk, current_event.pk)
        self._save_session_fields(session.pk, current_event.pk)

        # T2: raising (or unlimiting) capacity frees seats — promote waiters.
        new_limit = form.cleaned_data.get("participants_limit") or 0
        if new_limit == 0 or new_limit > session.participants_limit:
            self.request.services.waitlist_promotion.fill_freed_seats(
                session_id=proposal_id
            )

        messages.success(self.request, _("Proposal updated successfully."))
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)


class ProposalCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new session from the organizer panel."""

    request: PanelRequest

    def _get_form(
        self, current_event: EventDTO, data: QueryDict | None = None
    ) -> forms.Form:
        categories = self.request.di.uow.proposal_categories.list_by_event(
            current_event.pk
        )
        choices = [(c.pk, c.name) for c in categories]
        form_class = create_proposal_form(choices)
        return form_class(data) if data is not None else form_class()

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "proposals"
        context["form"] = self._get_form(current_event)
        return TemplateResponse(self.request, "panel/proposal-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = self._get_form(current_event, self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "proposals"
            context["form"] = form
            return TemplateResponse(self.request, "panel/proposal-create.html", context)

        title = form.cleaned_data["title"]
        sphere_id = self.request.context.current_sphere_id
        session_slug = make_unique_slug(
            title,
            "session",
            lambda s: self.request.di.uow.sessions.slug_exists(sphere_id, s),
        )

        self.request.di.uow.sessions.create(
            SessionData(
                category_id=int(form.cleaned_data["category_id"]),
                contact_email=form.cleaned_data.get("contact_email") or "",
                description=form.cleaned_data.get("description") or "",
                display_name=form.cleaned_data["display_name"],
                duration=form.cleaned_data.get("duration") or "",
                min_age=form.cleaned_data.get("min_age") or 0,
                needs=form.cleaned_data.get("needs") or "",
                participants_limit=form.cleaned_data.get("participants_limit") or 0,
                presenter_id=None,
                requirements=form.cleaned_data.get("requirements") or "",
                slug=session_slug,
                sphere_id=sphere_id,
                status=SessionStatus.PENDING,
                title=title,
            ),
            tag_ids=[],
        )
        messages.success(self.request, _("Proposal created successfully."))
        return redirect("panel:proposals", slug=slug)


class ProposalRejectActionView(PanelAccessMixin, EventContextMixin, View):
    """Reject a proposal (POST only)."""

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

        self.request.di.uow.sessions.update(
            session.pk, {"status": SessionStatus.REJECTED}
        )
        messages.success(self.request, _("Proposal rejected."))
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
