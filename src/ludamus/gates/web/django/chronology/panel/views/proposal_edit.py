# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""Proposal create and edit pages — the two form-handling proposal views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    format_field_value,
)
from ludamus.gates.web.django.forms import create_proposal_form, field_descriptors
from ludamus.pacts import (
    NotFoundError,
    PersonalDataFieldValueData,
    SessionContentEditData,
    SessionData,
    SessionFieldValueData,
    SessionStatus,
    SessionUpdateData,
)
from ludamus.pacts.legacy import resolve_cover_image
from ludamus.pacts.panel import ProposalDraft
from ludamus.pacts.services import DatabaseConstraintError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django import forms
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts import (
        EventDTO,
        FacilitatorDTO,
        FacilitatorListItemDTO,
        PersonalDataFieldDTO,
        ProposalCategoryDTO,
        SessionDTO,
        SessionFieldDTO,
        SessionFieldRequirementDTO,
        TimeSlotDTO,
        TrackDTO,
    )

    PersonalFieldItems = list[
        tuple[PersonalDataFieldDTO, str | list[str] | bool | None]
    ]
    FacilitatorPersonalData = list[tuple[FacilitatorDTO, str, PersonalFieldItems]]


def resolve_category(
    request: PanelRequest, event: EventDTO, data: QueryDict
) -> ProposalCategoryDTO | None:
    # The category drives which session fields render, but it is picked inside
    # the same form — so read it back from the submission (or the HTMX swap)
    # and fall back to the event's first category on a fresh page.
    if not (categories := request.di.uow.proposal_categories.list_by_event(event.pk)):
        return None
    raw = data.get("category_id", "").strip()
    if raw.isdigit():
        chosen = next((c for c in categories if c.pk == int(raw)), None)
        if chosen is not None:
            return chosen
    return categories[0]


@dataclass(frozen=True)
class OrphanFieldValue:
    """A stored answer to a question the session's category no longer asks."""

    field_id: int
    name: str
    display_value: str


def _option_labels(field: SessionFieldDTO | None) -> dict[str, str]:
    return {option.value: option.label for option in field.options} if field else {}


def session_field_requirements(
    request: PanelRequest, category: ProposalCategoryDTO | None
) -> list[SessionFieldRequirementDTO]:
    if category is None:
        return []
    return request.di.uow.proposal_categories.list_session_field_requirements(
        category.pk
    )


def build_create_form(
    request: PanelRequest,
    event: EventDTO,
    category: ProposalCategoryDTO | None,
    data: QueryDict | None = None,
) -> forms.Form:
    categories = request.di.uow.proposal_categories.list_by_event(event.pk)
    facilitators = request.di.uow.facilitators.list_by_event(event.pk)
    form_class = create_proposal_form(
        [(c.pk, c.name) for c in categories],
        facilitators=[(f.pk, f.display_name) for f in facilitators],
        requirements=session_field_requirements(request, category),
        category=category,
    )
    if data is not None:
        return form_class(data)
    # Preselect the resolved category so the picker agrees with the fields
    # rendered beneath it.
    return form_class(initial={"category_id": category.pk} if category else None)


def collect_session_field_inputs(
    *, requirements: Sequence[SessionFieldRequirementDTO], form: forms.Form
) -> dict[int, str | list[str] | bool]:
    # Only the category's own fields are read back; a value the category no
    # longer asks for is left untouched rather than blanked.
    inputs: dict[int, str | list[str] | bool] = {}
    for req in requirements:
        key = f"session_{req.field.slug}"
        value = form.cleaned_data.get(key)
        if req.field.allow_custom and not value:
            value = form.cleaned_data.get(f"{key}_custom", "")
        inputs[req.field.pk] = value if value is not None else ""
    return inputs


def collect_session_field_values(
    *,
    session_id: int,
    requirements: Sequence[SessionFieldRequirementDTO],
    form: forms.Form,
) -> list[SessionFieldValueData]:
    values: list[SessionFieldValueData] = []
    for field_id, value in collect_session_field_inputs(
        requirements=requirements, form=form
    ).items():
        values.append(
            SessionFieldValueData(session_id=session_id, field_id=field_id, value=value)
        )
    return values


def session_category(
    *, request: PanelRequest, event_pk: int, session: SessionDTO
) -> ProposalCategoryDTO | None:
    # A submitted / HTMX-swapped category wins, so the fields and the orphan
    # list follow the picker; otherwise fall back to the stored one.
    categories = request.di.uow.proposal_categories.list_by_event(event_pk)
    data = request.POST if request.method == "POST" else request.GET
    raw = data.get("category_id", "").strip()
    if raw.isdigit() and (
        chosen := next((c for c in categories if c.pk == int(raw)), None)
    ):
        return chosen
    return next((c for c in categories if c.pk == session.category_id), None)


def build_edit_form(
    *,
    request: PanelRequest,
    event_pk: int,
    category: ProposalCategoryDTO | None,
    session: SessionDTO,
    data: QueryDict | None = None,
) -> forms.Form:
    requirements = session_field_requirements(request, category)
    categories = request.di.uow.proposal_categories.list_by_event(event_pk)
    form_class = create_proposal_form(
        [(c.pk, c.name) for c in categories],
        requirements=requirements,
        category=category,
    )
    if data is not None:
        return form_class(data, request.FILES)
    initial: dict[str, Any] = {
        "title": session.title,
        "display_name": session.display_name,
        "description": session.description,
        "contact_email": session.contact_email,
        "participants_limit": session.participants_limit,
        "min_age": session.min_age,
        "duration": session.duration,
        "category_id": session.category_id,
        "cover_image": session.cover_image_url or None,
    }
    stored = {
        fv.field_id: fv.value
        for fv in request.di.uow.sessions.read_field_values(session.pk)
    }
    for req in requirements:
        if req.field.pk in stored:
            initial[f"session_{req.field.slug}"] = stored[req.field.pk]
    return form_class(initial=initial)


def orphan_values(
    *, request: PanelRequest, event_pk: int, session: SessionDTO
) -> list[OrphanFieldValue]:
    category = session_category(request=request, event_pk=event_pk, session=session)
    asked_pks = {req.field.pk for req in session_field_requirements(request, category)}
    fields_by_pk = {
        f.pk: f for f in request.di.uow.session_fields.list_by_event(event_pk)
    }
    return [
        OrphanFieldValue(
            field_id=value.field_id,
            name=value.field_question or value.field_name,
            display_value=format_field_value(
                value=value.value,
                labels=_option_labels(fields_by_pk.get(value.field_id)),
            ),
        )
        for value in request.di.uow.sessions.read_field_values(session.pk)
        if value.field_id not in asked_pks
    ]


def field_context(
    *,
    request: PanelRequest,
    event: EventDTO,
    session: SessionDTO,
    category: ProposalCategoryDTO | None,
    form: forms.Form,
) -> dict[str, Any]:
    # The session-fields fieldset, whether it renders inside the edit page or
    # on its own after a category swap.
    return {
        "field_descriptors": field_descriptors(
            "session", session_field_requirements(request, category), form
        ),
        "orphan_values": orphan_values(
            request=request, event_pk=event.pk, session=session
        ),
        "fields_url": reverse(
            "panel:proposal-edit-fields",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        ),
    }


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

    def _get_track_context(
        self, event_pk: int, proposal_id: int
    ) -> tuple[list[TrackDTO], set[int]]:
        all_tracks = self.request.di.uow.tracks.list_by_event(event_pk)
        assigned_pks = set(self.request.di.uow.sessions.read_track_ids(proposal_id))
        return all_tracks, assigned_pks

    def _submitted_ids(
        self, *, flag: str, key: str, valid_pks: set[int]
    ) -> list[int] | None:
        # None means "this section wasn't part of the submission" — an empty
        # list means the organizer cleared it. Ids the event doesn't own are
        # dropped rather than written.
        if self.request.POST.get(flag) != "1":
            return None
        submitted = {
            int(raw) for raw in self.request.POST.getlist(key) if raw.isdigit()
        }
        return list(submitted & valid_pks)

    def _collect_track_ids(self, event_pk: int) -> list[int] | None:
        return self._submitted_ids(
            flag="tracks_submitted",
            key="track_ids",
            valid_pks={
                t.pk for t in self.request.di.uow.tracks.list_by_event(event_pk)
            },
        )

    def _get_time_slot_context(
        self, event_pk: int, proposal_id: int
    ) -> tuple[list[TimeSlotDTO], set[int]]:
        all_time_slots = self.request.di.uow.time_slots.list_by_event(event_pk)
        assigned_pks = set(
            self.request.di.uow.sessions.read_preferred_time_slot_ids(proposal_id)
        )
        return all_time_slots, assigned_pks

    def _collect_time_slot_ids(self, event_pk: int) -> list[int] | None:
        return self._submitted_ids(
            flag="time_slots_submitted",
            key="time_slot_ids",
            valid_pks={
                ts.pk for ts in self.request.di.uow.time_slots.list_by_event(event_pk)
            },
        )

    def _get_facilitator_personal_data(
        self, event_pk: int, proposal_id: int
    ) -> FacilitatorPersonalData:
        fields = self.request.di.uow.personal_data_fields.list_by_event(event_pk)
        if not fields:
            return []
        assigned = self.request.di.uow.sessions.read_facilitators(proposal_id)
        result: FacilitatorPersonalData = []
        for facilitator in assigned:
            personal_data_field_values = self.request.di.uow.personal_data_field_values
            values = personal_data_field_values.read_for_facilitator_event(
                facilitator.pk, event_pk
            )
            items = [(field, values.get(field.slug)) for field in fields]
            result.append(
                (facilitator, f"facilitator_{facilitator.pk}_personal", items)
            )
        return result

    def _read_post_field_value(
        self, prefix: str, field: PersonalDataFieldDTO
    ) -> str | list[str] | bool:
        key = f"{prefix}_{field.slug}"
        if field.field_type == "checkbox":
            return self.request.POST.get(key) == "true"
        if field.is_multiple:
            return self.request.POST.getlist(key)
        value = self.request.POST.get(key, "")
        if field.allow_custom and not value:
            value = self.request.POST.get(f"{key}_custom", "")
        return value

    def _get_facilitator_personal_data_post(
        self, event_pk: int, proposal_id: int
    ) -> FacilitatorPersonalData:
        fields = self.request.di.uow.personal_data_fields.list_by_event(event_pk)
        if not fields:
            return []
        assigned = self.request.di.uow.sessions.read_facilitators(proposal_id)
        result: FacilitatorPersonalData = []
        for facilitator in assigned:
            prefix = f"facilitator_{facilitator.pk}_personal"
            items: PersonalFieldItems = [
                (field, self._read_post_field_value(prefix, field)) for field in fields
            ]
            result.append((facilitator, prefix, items))
        return result

    def _collect_personal_data(
        self, event_pk: int
    ) -> dict[int, list[PersonalDataFieldValueData]] | None:
        if self.request.POST.get("personal_data_submitted") != "1":
            return None
        raw_ids = self.request.POST.getlist("personal_data_facilitator_ids")
        submitted_ids = {int(fid) for fid in raw_ids if fid.isdigit()}
        valid_pks = {
            f.pk for f in self.request.di.uow.facilitators.list_by_event(event_pk)
        }
        fields = self.request.di.uow.personal_data_fields.list_by_event(event_pk)
        result: dict[int, list[PersonalDataFieldValueData]] = {}
        for facilitator_id in submitted_ids & valid_pks:
            prefix = f"facilitator_{facilitator_id}_personal"
            entries = [
                PersonalDataFieldValueData(
                    facilitator_id=facilitator_id,
                    event_id=event_pk,
                    field_id=field.pk,
                    value=self._read_post_field_value(prefix, field),
                )
                for field in fields
            ]
            result[facilitator_id] = entries
        return result

    def _collect_facilitator_ids(self, event_pk: int) -> list[int] | None:
        return self._submitted_ids(
            flag="facilitators_submitted",
            key="facilitator_ids",
            valid_pks={
                f.pk for f in self.request.di.uow.facilitators.list_by_event(event_pk)
            },
        )

    def _collect_remove_field_ids(
        self, event_pk: int, session: SessionDTO
    ) -> list[int]:
        raw_ids = self.request.POST.getlist("remove_field_ids")
        submitted = {int(fid) for fid in raw_ids if fid.isdigit()}
        # Only answers the category no longer asks for may be removed here; the
        # rest are edited through their own inputs.
        orphan_pks = {
            orphan.field_id
            for orphan in orphan_values(
                request=self.request, event_pk=event_pk, session=session
            )
        }
        return list(submitted & orphan_pks)

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

        all_facilitators, assigned_pks = self._get_facilitator_context(
            current_event.pk, proposal_id
        )
        category = session_category(
            request=self.request, event_pk=current_event.pk, session=session
        )
        form = build_edit_form(
            request=self.request,
            event_pk=current_event.pk,
            category=category,
            session=session,
        )
        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["form"] = form
        context.update(
            field_context(
                request=self.request,
                event=current_event,
                session=session,
                category=category,
                form=form,
            )
        )
        all_tracks, assigned_track_pks = self._get_track_context(
            current_event.pk, proposal_id
        )
        all_time_slots, assigned_time_slot_pks = self._get_time_slot_context(
            current_event.pk, proposal_id
        )
        context["all_facilitators"] = all_facilitators
        context["assigned_facilitator_pks"] = assigned_pks
        context["all_tracks"] = all_tracks
        context["assigned_track_pks"] = assigned_track_pks
        context["all_time_slots"] = all_time_slots
        context["assigned_time_slot_pks"] = assigned_time_slot_pks
        context["facilitator_personal_data"] = self._get_facilitator_personal_data(
            current_event.pk, proposal_id
        )
        return TemplateResponse(self.request, "panel/proposal-edit.html", context)

    def _render_invalid(
        self,
        context: dict[str, Any],
        *,
        form: forms.Form,
        session: SessionDTO,
        event: EventDTO,
    ) -> HttpResponse:
        event_pk = event.pk
        all_facilitators, assigned_pks = self._get_facilitator_context(
            event_pk, session.pk
        )
        all_tracks, assigned_track_pks = self._get_track_context(event_pk, session.pk)
        all_time_slots, assigned_time_slot_pks = self._get_time_slot_context(
            event_pk, session.pk
        )
        # Prefer the invalid submission over persisted values so in-progress
        # selections survive the re-render.
        submitted_facilitators = self._collect_facilitator_ids(event_pk)
        if submitted_facilitators is not None:
            assigned_pks = set(submitted_facilitators)
        if (submitted_tracks := self._collect_track_ids(event_pk)) is not None:
            assigned_track_pks = set(submitted_tracks)
        if (submitted_slots := self._collect_time_slot_ids(event_pk)) is not None:
            assigned_time_slot_pks = set(submitted_slots)
        personal_data = (
            self._get_facilitator_personal_data_post(event_pk, session.pk)
            if (self.request.POST.get("personal_data_submitted") == "1")
            else self._get_facilitator_personal_data(event_pk, session.pk)
        )
        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["form"] = form
        context["all_facilitators"] = all_facilitators
        context["assigned_facilitator_pks"] = assigned_pks
        context.update(
            field_context(
                request=self.request,
                event=event,
                session=session,
                category=session_category(
                    request=self.request, event_pk=event_pk, session=session
                ),
                form=form,
            )
        )
        context["all_tracks"] = all_tracks
        context["assigned_track_pks"] = assigned_track_pks
        context["all_time_slots"] = all_time_slots
        context["assigned_time_slot_pks"] = assigned_time_slot_pks
        context["facilitator_personal_data"] = personal_data
        return TemplateResponse(self.request, "panel/proposal-edit.html", context)

    def post(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
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

        category = session_category(
            request=self.request, event_pk=current_event.pk, session=session
        )
        form = build_edit_form(
            request=self.request,
            event_pk=current_event.pk,
            category=category,
            session=session,
            data=self.request.POST,
        )
        if not form.is_valid():
            return self._render_invalid(
                context, form=form, session=session, event=current_event
            )

        # A DB constraint/data error surfaces as an inline form error (input
        # preserved), not a bare 500 the user reads as a transient glitch.
        try:
            self._write_content_edit(
                current_event=current_event,
                session=session,
                form=form,
                category=category,
            )
        except DatabaseConstraintError:
            messages.error(
                self.request,
                _("Couldn't save your changes. Please check your input and try again."),
            )
            return self._render_invalid(
                context, form=form, session=session, event=current_event
            )

        messages.success(self.request, _("Proposal updated successfully."))
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)

    def _write_content_edit(
        self,
        *,
        current_event: EventDTO,
        session: SessionDTO,
        form: forms.Form,
        category: ProposalCategoryDTO | None,
    ) -> None:
        # One savepoint around every write so a DB constraint/data error rolls
        # the whole edit back and re-raises DatabaseConstraintError for the
        # caller to surface.
        update_data: SessionUpdateData = {
            "category_id": int(form.cleaned_data["category_id"]),
            "title": form.cleaned_data["title"],
            "display_name": form.cleaned_data["display_name"],
            "description": form.cleaned_data.get("description") or "",
            "contact_email": form.cleaned_data.get("contact_email") or "",
            "participants_limit": form.cleaned_data.get("participants_limit") or 0,
            "min_age": form.cleaned_data.get("min_age") or 0,
            "duration": form.cleaned_data.get("duration") or "",
        }
        cover = resolve_cover_image(form.cleaned_data.get("cover_image"))
        if cover is not None:
            update_data["cover_image"] = cover
        requirements = session_field_requirements(self.request, category)
        remove_field_ids = self._collect_remove_field_ids(current_event.pk, session)
        with self.request.di.uow.savepoint():
            self.request.services.session_content_edit.apply(
                session_id=session.pk,
                event_id=current_event.pk,
                user_id=self.request.context.current_user_id,
                data=SessionContentEditData(
                    update=update_data,
                    field_values=collect_session_field_values(
                        session_id=session.pk, requirements=requirements, form=form
                    ),
                    facilitator_ids=self._collect_facilitator_ids(current_event.pk),
                    track_ids=self._collect_track_ids(current_event.pk),
                    time_slot_ids=self._collect_time_slot_ids(current_event.pk),
                    remove_field_ids=remove_field_ids,
                ),
            )

            personal_data = self._collect_personal_data(current_event.pk)
            if personal_data is not None:
                for facilitator_id, entries in personal_data.items():
                    service = self.request.services.personal_data_field_values
                    service.update_personal_data(
                        event_id=current_event.pk,
                        facilitator_id=facilitator_id,
                        entries=entries,
                        user_id=self.request.context.current_user_id,
                    )

            # T2: raising (or unlimiting) capacity frees seats — promote waiters.
            new_limit = form.cleaned_data.get("participants_limit") or 0
            if new_limit == 0 or new_limit > session.participants_limit:
                self.request.services.waitlist_promotion.fill_freed_seats(
                    session_id=session.pk
                )


class ProposalCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new session from the organizer panel."""

    request: PanelRequest

    def _render(
        self,
        context: dict[str, Any],
        *,
        current_event: EventDTO,
        category: ProposalCategoryDTO | None,
        form: forms.Form,
    ) -> HttpResponse:
        context["active_nav"] = "proposals"
        context["form"] = form
        context["category"] = category
        context["all_facilitators"] = self.request.di.uow.facilitators.list_by_event(
            current_event.pk
        )
        # The picker partial keys checked state off pks, so translate the
        # form's raw (possibly re-submitted) values back to ints.
        raw_ids: list[str] = []
        if "facilitator_ids" in form.fields:
            raw_ids = form["facilitator_ids"].value() or []
        context["assigned_facilitator_pks"] = {
            int(v) for v in raw_ids if str(v).isdigit()
        } & {f.pk for f in context["all_facilitators"]}
        all_time_slots = self.request.di.uow.time_slots.list_by_event(current_event.pk)
        context["all_time_slots"] = all_time_slots
        # Slots live outside the form (checkbox list, like on edit), so an
        # invalid submission re-reads the in-progress selection from POST.
        context["assigned_time_slot_pks"] = {
            int(v) for v in self.request.POST.getlist("time_slot_ids") if v.isdigit()
        } & {ts.pk for ts in all_time_slots}
        context["field_descriptors"] = field_descriptors(
            "session", session_field_requirements(self.request, category), form
        )
        # A session being created has no stored answers, so it can never have
        # any outside its category.
        context["orphan_values"] = []
        context["fields_url"] = reverse(
            "panel:proposal-create-fields", kwargs={"slug": current_event.slug}
        )
        return TemplateResponse(self.request, "panel/proposal-create.html", context)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        category = resolve_category(self.request, current_event, self.request.GET)
        return self._render(
            context,
            current_event=current_event,
            category=category,
            form=build_create_form(self.request, current_event, category),
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        category = resolve_category(self.request, current_event, self.request.POST)
        form = build_create_form(
            self.request, current_event, category, self.request.POST
        )
        if not form.is_valid():
            return self._render(
                context, current_event=current_event, category=category, form=form
            )

        # A DB constraint/data error surfaces as an inline form error (input
        # preserved), not a bare 500 the user reads as a transient glitch.
        try:
            proposal_id = self._write_new_session(
                current_event=current_event, category=category, form=form
            )
        except DatabaseConstraintError:
            messages.error(
                self.request,
                _("Couldn't save the session. Please check your input and try again."),
            )
            return self._render(
                context, current_event=current_event, category=category, form=form
            )
        messages.success(self.request, _("Proposal created successfully."))
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)

    def _write_new_session(
        self,
        *,
        current_event: EventDTO,
        category: ProposalCategoryDTO | None,
        form: forms.Form,
    ) -> int:
        title = form.cleaned_data["title"]
        # The form's MultipleChoiceField already validated each id against the
        # event's facilitators, so the cleaned list is event-scoped.
        facilitator_ids = [int(fid) for fid in form.cleaned_data["facilitator_ids"]]
        requirements = session_field_requirements(self.request, category)
        submitted_slot_ids = {
            int(v) for v in self.request.POST.getlist("time_slot_ids") if v.isdigit()
        }
        valid_slot_pks = {
            ts.pk
            for ts in self.request.di.uow.time_slots.list_by_event(current_event.pk)
        }
        return self.request.services.proposal_panel.create_proposal(
            event_id=current_event.pk,
            draft=ProposalDraft(
                data=SessionData(
                    category_id=int(form.cleaned_data["category_id"]),
                    event_id=current_event.pk,
                    contact_email=form.cleaned_data.get("contact_email") or "",
                    description=form.cleaned_data.get("description") or "",
                    display_name=form.cleaned_data["display_name"],
                    duration=form.cleaned_data.get("duration") or "",
                    min_age=form.cleaned_data.get("min_age") or 0,
                    participants_limit=form.cleaned_data.get("participants_limit") or 0,
                    presenter_id=None,
                    status=SessionStatus.PENDING,
                    title=title,
                ),
                base_slug=slugify(title),
                facilitator_ids=facilitator_ids,
                field_values=(
                    collect_session_field_inputs(requirements=requirements, form=form)
                    if requirements
                    else {}
                ),
                time_slot_ids=list(submitted_slot_ids & valid_slot_pks),
            ),
        )


class ProposalCreateFieldsComponentView(PanelAccessMixin, EventContextMixin, View):
    """Re-render the create form's session fields for the picked category."""

    request: PanelRequest
    http_method_names = ("get",)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        # A category swap re-renders one fieldset: it needs the event, not the
        # page's event list and stats.
        if (current_event := self.get_event(slug)) is None:
            return redirect("panel:index")

        category = resolve_category(self.request, current_event, self.request.GET)
        requirements = session_field_requirements(self.request, category)
        form = build_create_form(self.request, current_event, category)
        return TemplateResponse(
            self.request,
            "panel/parts/proposal-session-fields.html",
            {
                "field_descriptors": field_descriptors("session", requirements, form),
                "form": form,
                "category": category,
                "orphan_values": [],
            },
        )


class ProposalEditFieldsComponentView(PanelAccessMixin, EventContextMixin, View):
    """Re-render the edit form's session fields for the picked category."""

    request: PanelRequest
    http_method_names = ("get",)

    def get(self, _request: PanelRequest, slug: str, proposal_id: int) -> HttpResponse:
        # Same as the create component: one fieldset, no page chrome.
        if (current_event := self.get_event(slug)) is None:
            return redirect("panel:index")

        try:
            session = self.request.services.proposal_panel.read_proposal(
                event_id=current_event.pk, proposal_id=proposal_id
            )
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        category = session_category(
            request=self.request, event_pk=current_event.pk, session=session
        )
        form = build_edit_form(
            request=self.request,
            event_pk=current_event.pk,
            category=category,
            session=session,
        )
        context: dict[str, Any] = {
            "form": form,
            **field_context(
                request=self.request,
                event=current_event,
                session=session,
                category=category,
                form=form,
            ),
        }
        return TemplateResponse(
            self.request, "panel/parts/proposal-session-fields.html", context
        )
