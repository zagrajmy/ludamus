# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""Proposal/session list, detail, edit, create, and action views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    make_unique_slug,
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
from ludamus.pacts.chronology import (
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    ProposalScheduledError,
)
from ludamus.pacts.legacy import resolve_cover_image

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django import forms
    from django.http import HttpResponse, QueryDict
    from django.utils.functional import _StrPromise

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
    categories = request.di.uow.proposal_categories.list_by_event(event.pk)
    if not categories:
        return None
    raw = data.get("category_id", "").strip()
    if raw.isdigit():
        chosen = next((c for c in categories if c.pk == int(raw)), None)
        if chosen is not None:
            return chosen
    return categories[0]


def _display_field_value(field: SessionFieldDTO | None, raw: object) -> object:
    # Stored answers hold option *values*; show the option labels an organizer
    # would recognise. Booleans and free text pass through.
    if field is None or isinstance(raw, bool):
        return raw
    labels = {option.value: option.label for option in field.options}
    if isinstance(raw, list):
        return ", ".join(labels.get(v) or v for v in raw)
    if isinstance(raw, str):
        return labels.get(raw, raw)
    return raw


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


def collect_session_field_values(
    *,
    session_id: int,
    requirements: Sequence[SessionFieldRequirementDTO],
    form: forms.Form,
) -> list[SessionFieldValueData]:
    # Only the category's own fields are read back; a value the category no
    # longer asks for is left untouched rather than blanked.
    values: list[SessionFieldValueData] = []
    for req in requirements:
        key = f"session_{req.field.slug}"
        value = form.cleaned_data.get(key)
        if req.field.allow_custom and not value:
            value = form.cleaned_data.get(f"{key}_custom", "")
        values.append(
            SessionFieldValueData(
                session_id=session_id,
                field_id=req.field.pk,
                value=value if value is not None else "",
            )
        )
    return values


_PROPOSALS_PAGE_SIZE = 50  # ponytail: revisit after dogfooding

# Filter-only pseudo-status: scheduling lives on the agenda item, not on
# SessionStatus, but organizers still need "show me what's placed".
SCHEDULED_FILTER = "scheduled"


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

        categories = self.request.di.uow.proposal_categories.list_by_event(
            current_event.pk
        )
        category_raw = self.request.GET.get("category", "").strip()
        filter_category_pk = int(category_raw) if category_raw.isdigit() else None
        if filter_category_pk not in {c.pk for c in categories}:
            filter_category_pk = None

        # Default (no status param) shows every proposal: an event whose
        # sessions weren't created via proposals should not look empty on first
        # load. Explicit picks (a real status or the "scheduled" pseudo-filter)
        # still narrow the list.
        status_raw = self.request.GET.get("status")
        filter_status: str | None = (
            status_raw
            if status_raw == SCHEDULED_FILTER or status_raw in set(SessionStatus)
            else None
        )

        # Scheduled is a placement fact, not a status: the "scheduled" option
        # filters on agenda-item existence, and picking a real status excludes
        # scheduled sessions so the backlog views stay clean.
        if filter_status == SCHEDULED_FILTER:
            status_filter, scheduled_filter = None, True
        elif filter_status is not None:
            status_filter, scheduled_filter = SessionStatus(filter_status), False
        else:
            status_filter, scheduled_filter = None, None

        all_proposals = self.request.di.uow.sessions.list_sessions_by_event(
            current_event.pk,
            {
                "field_filters": field_filters or None,
                "search": search,
                "track_pk": filter_track_pk,
                "category_pk": filter_category_pk,
                "status": status_filter,
                "scheduled": scheduled_filter,
            },
        )
        # ponytail: paginate the already-loaded list in the view. The repo
        # loads all matching rows today anyway; DB-level slicing is a future
        # concern if an event's proposal count grows past a few thousand.
        page_obj = Paginator(all_proposals, _PROPOSALS_PAGE_SIZE).get_page(
            self.request.GET.get("page")
        )

        context["proposals"] = list(page_obj.object_list)
        context["page_obj"] = page_obj
        context["deleted_proposals"] = (
            self.request.di.uow.sessions.list_deleted_by_event(current_event.pk)
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
        context["categories"] = categories
        context["filter_category_pk"] = filter_category_pk
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
        context["filter_status"] = filter_status
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

    def _category_choices(self, event_pk: int) -> list[tuple[int, str]]:
        categories = self.request.di.uow.proposal_categories.list_by_event(event_pk)
        return [(c.pk, c.name) for c in categories]

    def _get_track_context(
        self, event_pk: int, proposal_id: int
    ) -> tuple[list[TrackDTO], set[int]]:
        all_tracks = self.request.di.uow.tracks.list_by_event(event_pk)
        assigned_pks = set(self.request.di.uow.sessions.read_track_ids(proposal_id))
        return all_tracks, assigned_pks

    def _collect_track_ids(self, event_pk: int) -> list[int] | None:
        if self.request.POST.get("tracks_submitted") != "1":
            return None
        raw_ids = self.request.POST.getlist("track_ids")
        submitted_ids = {int(tid) for tid in raw_ids if tid.isdigit()}
        valid_pks = {t.pk for t in self.request.di.uow.tracks.list_by_event(event_pk)}
        return list(submitted_ids & valid_pks)

    def _get_time_slot_context(
        self, event_pk: int, proposal_id: int
    ) -> tuple[list[TimeSlotDTO], set[int]]:
        all_time_slots = self.request.di.uow.time_slots.list_by_event(event_pk)
        assigned_pks = set(
            self.request.di.uow.sessions.read_preferred_time_slot_ids(proposal_id)
        )
        return all_time_slots, assigned_pks

    def _collect_time_slot_ids(self, event_pk: int) -> list[int] | None:
        if self.request.POST.get("time_slots_submitted") != "1":
            return None
        raw_ids = self.request.POST.getlist("time_slot_ids")
        submitted_ids = {int(tid) for tid in raw_ids if tid.isdigit()}
        valid_pks = {
            ts.pk for ts in self.request.di.uow.time_slots.list_by_event(event_pk)
        }
        return list(submitted_ids & valid_pks)

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
        if self.request.POST.get("facilitators_submitted") != "1":
            return None
        raw_ids = self.request.POST.getlist("facilitator_ids")
        submitted_ids = {int(fid) for fid in raw_ids if fid.isdigit()}
        all_facilitators = self.request.di.uow.facilitators.list_by_event(event_pk)
        valid_pks = {f.pk for f in all_facilitators}
        return list(submitted_ids & valid_pks)

    def _collect_remove_field_ids(self, event_pk: int, proposal_id: int) -> list[int]:
        raw_ids = self.request.POST.getlist("remove_field_ids")
        submitted = {int(fid) for fid in raw_ids if fid.isdigit()}
        # Only answers the category no longer asks for may be removed here; the
        # rest are edited through their own inputs.
        orphan_pks = {
            orphan["field_id"] for orphan in self._orphan_values(event_pk, proposal_id)
        }
        return list(submitted & orphan_pks)

    def _session_category(
        self, event_pk: int, proposal_id: int
    ) -> ProposalCategoryDTO | None:
        # A submitted / HTMX-swapped category wins, so the fields and the
        # orphan list follow the picker; otherwise fall back to the stored one.
        categories = self.request.di.uow.proposal_categories.list_by_event(event_pk)
        data = self.request.POST if self.request.method == "POST" else self.request.GET
        raw = data.get("category_id", "").strip()
        if raw.isdigit() and (
            chosen := next((c for c in categories if c.pk == int(raw)), None)
        ):
            return chosen
        category_id = self.request.di.uow.sessions.read(proposal_id).category_id
        return next((c for c in categories if c.pk == category_id), None)

    def _build_form(
        self,
        event_pk: int,
        category: ProposalCategoryDTO | None,
        session: SessionDTO,
        data: QueryDict | None = None,
    ) -> forms.Form:
        requirements = session_field_requirements(self.request, category)
        form_class = create_proposal_form(
            self._category_choices(event_pk),
            requirements=requirements,
            category=category,
        )
        if data is not None:
            return form_class(data, self.request.FILES)
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
            for fv in self.request.di.uow.sessions.read_field_values(session.pk)
        }
        for req in requirements:
            if req.field.pk in stored:
                initial[f"session_{req.field.slug}"] = stored[req.field.pk]
        return form_class(initial=initial)

    def _add_field_context(
        self,
        context: dict[str, Any],
        *,
        event_pk: int,
        proposal_id: int,
        category: ProposalCategoryDTO | None,
        form: forms.Form,
    ) -> None:
        context["field_descriptors"] = field_descriptors(
            "session", session_field_requirements(self.request, category), form
        )
        context["orphan_values"] = self._orphan_values(event_pk, proposal_id)
        context["fields_url"] = reverse(
            "panel:proposal-edit-fields",
            kwargs={"slug": context["current_event"].slug, "proposal_id": proposal_id},
        )

    def _orphan_values(self, event_pk: int, proposal_id: int) -> list[dict[str, Any]]:
        category = self._session_category(event_pk, proposal_id)
        asked_pks = {
            req.field.pk for req in session_field_requirements(self.request, category)
        }
        fields_by_pk = {
            f.pk: f for f in self.request.di.uow.session_fields.list_by_event(event_pk)
        }
        orphans: list[dict[str, Any]] = []
        for value in self.request.di.uow.sessions.read_field_values(proposal_id):
            if value.field_id in asked_pks:
                continue
            field = fields_by_pk.get(value.field_id)
            orphans.append(
                {
                    "field_id": value.field_id,
                    "name": value.field_question or value.field_name,
                    "display_value": _display_field_value(field, value.value),
                }
            )
        return orphans

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
        category = self._session_category(current_event.pk, proposal_id)
        form = self._build_form(current_event.pk, category, session)
        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["form"] = form
        self._add_field_context(
            context,
            event_pk=current_event.pk,
            proposal_id=proposal_id,
            category=category,
            form=form,
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
        event_pk: int,
    ) -> HttpResponse:
        all_facilitators, assigned_pks = self._get_facilitator_context(
            event_pk, session.pk
        )
        all_tracks, assigned_track_pks = self._get_track_context(event_pk, session.pk)
        all_time_slots, assigned_time_slot_pks = self._get_time_slot_context(
            event_pk, session.pk
        )
        # Prefer the invalid submission over persisted values so in-progress
        # selections survive the re-render.
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
        self._add_field_context(
            context,
            event_pk=event_pk,
            proposal_id=session.pk,
            category=self._session_category(event_pk, session.pk),
            form=form,
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
            session = self.request.di.uow.sessions.read(proposal_id)
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        session_event = self.request.di.uow.sessions.read_event(proposal_id)
        if session_event.pk != current_event.pk:
            messages.error(self.request, _("Proposal not found."))
            return redirect("panel:proposals", slug=slug)

        category = self._session_category(current_event.pk, proposal_id)
        form = self._build_form(current_event.pk, category, session, self.request.POST)
        if not form.is_valid():
            return self._render_invalid(
                context, form=form, session=session, event_pk=current_event.pk
            )

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
        remove_field_ids = self._collect_remove_field_ids(current_event.pk, proposal_id)
        self.request.services.session_content_edit.apply(
            session_id=proposal_id,
            event_id=current_event.pk,
            user_id=self.request.context.current_user_id,
            data=SessionContentEditData(
                update=update_data,
                field_values=collect_session_field_values(
                    session_id=proposal_id, requirements=requirements, form=form
                ),
                facilitator_ids=self._collect_facilitator_ids(current_event.pk),
                track_ids=self._collect_track_ids(current_event.pk),
                time_slot_ids=self._collect_time_slot_ids(current_event.pk),
                remove_field_ids=remove_field_ids,
            ),
        )

        if (personal_data := self._collect_personal_data(current_event.pk)) is not None:
            for facilitator_id, entries in personal_data.items():
                self.request.services.personal_data_field_values.update_personal_data(
                    event_id=current_event.pk,
                    facilitator_id=facilitator_id,
                    entries=entries,
                    user_id=self.request.context.current_user_id,
                )

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

        title = form.cleaned_data["title"]
        session_slug = make_unique_slug(
            title,
            "session",
            lambda s: self.request.di.uow.sessions.slug_exists(current_event.pk, s),
        )

        # The form's MultipleChoiceField already validated each id against the
        # event's facilitators, so the cleaned list is event-scoped.
        facilitator_ids = [int(fid) for fid in form.cleaned_data["facilitator_ids"]]
        proposal_id = self.request.di.uow.sessions.create(
            SessionData(
                category_id=int(form.cleaned_data["category_id"]),
                event_id=current_event.pk,
                contact_email=form.cleaned_data.get("contact_email") or "",
                description=form.cleaned_data.get("description") or "",
                display_name=form.cleaned_data["display_name"],
                duration=form.cleaned_data.get("duration") or "",
                min_age=form.cleaned_data.get("min_age") or 0,
                participants_limit=form.cleaned_data.get("participants_limit") or 0,
                presenter_id=None,
                slug=session_slug,
                status=SessionStatus.PENDING,
                title=title,
            ),
            facilitator_ids=facilitator_ids,
        )
        if requirements := session_field_requirements(self.request, category):
            self.request.di.uow.sessions.save_field_values(
                proposal_id,
                collect_session_field_values(
                    session_id=proposal_id, requirements=requirements, form=form
                ),
            )
        messages.success(self.request, _("Proposal created successfully."))
        return redirect("panel:proposal-detail", slug=slug, proposal_id=proposal_id)


class ProposalCreateFieldsComponentView(PanelAccessMixin, EventContextMixin, View):
    """Re-render the create form's session fields for the picked category."""

    request: PanelRequest
    http_method_names = ("get",)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
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


class ProposalEditFieldsComponentView(ProposalEditPageView):
    """Re-render the edit form's session fields for the picked category."""

    http_method_names = ("get",)

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

        category = self._session_category(current_event.pk, proposal_id)
        form = self._build_form(current_event.pk, category, session)
        self._add_field_context(
            context,
            event_pk=current_event.pk,
            proposal_id=proposal_id,
            category=category,
            form=form,
        )
        context["form"] = form
        return TemplateResponse(
            self.request, "panel/parts/proposal-session-fields.html", context
        )


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

        messages.success(self.request, _("Session deleted."))
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

        messages.success(self.request, _("Session restored."))
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
