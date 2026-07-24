# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""Proposal/session list, detail, edit, create, and action views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
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
from ludamus.pacts.services import DatabaseConstraintError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from django import forms
    from django.http import QueryDict
    from django.utils.functional import _StrPromise

    from ludamus.pacts import (
        EventDTO,
        FacilitatorDTO,
        PersonalDataFieldDTO,
        ProposalCategoryDTO,
        SessionDTO,
        SessionFieldDTO,
        SessionFieldRequirementDTO,
        SessionFieldValueDTO,
    )

    PersonalFieldItems = list[
        tuple[PersonalDataFieldDTO, str | list[str] | bool | None]
    ]
    FacilitatorPersonalData = list[tuple[FacilitatorDTO, str, PersonalFieldItems]]


class _HasPk(Protocol):
    # The three checkbox pickers hold unrelated DTOs; all the shared code needs
    # from them is a pk.
    pk: int


@dataclass(frozen=True)
class _Prepared:
    """What a proposal-form request resolves once, before rendering or saving."""

    session: SessionDTO | None
    category: ProposalCategoryDTO | None
    requirements: Sequence[SessionFieldRequirementDTO]
    form: forms.Form


@dataclass(frozen=True)
class OrphanFieldValue:
    """A stored answer to a question the session's category no longer asks."""

    field_id: int
    name: str
    display_value: str


def _display_field_value(
    field: SessionFieldDTO | None, stored: SessionFieldValueDTO
) -> str:
    # Stored answers hold option *values*; show the option labels an organizer
    # would recognise, and a checkbox as a word rather than "True".
    raw = stored.value
    if isinstance(raw, bool):
        return _("Yes") if raw else _("No")
    labels = {option.value: option.label for option in field.options} if field else {}
    if isinstance(raw, list):
        return ", ".join(labels.get(v) or v for v in raw)
    return labels.get(raw) or raw


def session_field_requirements(
    request: PanelRequest, category: ProposalCategoryDTO | None
) -> list[SessionFieldRequirementDTO]:
    if category is None:
        return []
    return request.di.uow.proposal_categories.list_session_field_requirements(
        category.pk
    )


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
        filter_track_multi = self.request.GET.get("track") == "multi"

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
                "multi_tracks": filter_track_multi or None,
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
        context["filter_track_multi"] = filter_track_multi
        # Value the other filter form echoes back so the track selection
        # round-trips. Empty string ("All tracks") must stay present in the
        # query, or the absent-param default re-selects the managed track.
        context["filter_track_value"] = (
            "multi"
            if filter_track_multi
            else str(filter_track_pk) if filter_track_pk is not None else ""
        )
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


class ProposalFormPageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new proposal or edit an existing one from the organizer panel."""

    request: PanelRequest

    def _load_session(
        self, slug: str, current_event: EventDTO, proposal_id: int | None
    ) -> tuple[SessionDTO | None, HttpResponse | None]:
        # None proposal_id is the create flow; otherwise the session must exist
        # and belong to this event.
        if proposal_id is None:
            return None, None
        try:
            session = self.request.di.uow.sessions.read(proposal_id)
        except NotFoundError:
            messages.error(self.request, _("Proposal not found."))
            return None, redirect("panel:proposals", slug=slug)
        if self.request.di.uow.sessions.read_event(proposal_id).pk != current_event.pk:
            messages.error(self.request, _("Proposal not found."))
            return None, redirect("panel:proposals", slug=slug)
        return session, None

    def _prepare(
        self,
        slug: str,
        current_event: EventDTO,
        proposal_id: int | None,
        data: QueryDict | None = None,
    ) -> _Prepared | HttpResponse:
        session, error = self._load_session(slug, current_event, proposal_id)
        if error is not None:
            return error
        categories = self.request.di.uow.proposal_categories.list_by_event(
            current_event.pk
        )
        category = self._resolve_category(categories, session)
        requirements = session_field_requirements(self.request, category)
        return _Prepared(
            session=session,
            category=category,
            requirements=requirements,
            form=self._build_form(
                categories=categories,
                category=category,
                requirements=requirements,
                session=session,
                data=data,
            ),
        )

    def _resolve_category(
        self, categories: Sequence[ProposalCategoryDTO], session: SessionDTO | None
    ) -> ProposalCategoryDTO | None:
        # The category drives which session fields render, but it is picked
        # inside the same form — a submitted / HTMX-swapped value wins, then the
        # stored one (edit), then the event's first category (fresh create).
        if not categories:
            return None
        data = self.request.POST if self.request.method == "POST" else self.request.GET
        raw = data.get("category_id", "").strip()
        if raw.isdigit() and (
            chosen := next((c for c in categories if c.pk == int(raw)), None)
        ):
            return chosen
        if session is not None:
            return next((c for c in categories if c.pk == session.category_id), None)
        return categories[0]

    def _build_form(
        self,
        *,
        categories: Sequence[ProposalCategoryDTO],
        category: ProposalCategoryDTO | None,
        requirements: Sequence[SessionFieldRequirementDTO],
        session: SessionDTO | None,
        data: QueryDict | None,
    ) -> forms.Form:
        form_class = create_proposal_form(
            [(c.pk, c.name) for c in categories],
            requirements=requirements,
            category=category,
        )
        if data is not None:
            return form_class(data, self.request.FILES)
        if session is None:
            # Preselect the resolved category so the picker agrees with the
            # fields rendered beneath it.
            return form_class(
                initial={"category_id": category.pk} if category else None
            )
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

    def _add_field_context(self, context: dict[str, Any], prepared: _Prepared) -> None:
        current_event = context["current_event"]
        session = prepared.session
        context["field_descriptors"] = field_descriptors(
            "session", prepared.requirements, prepared.form
        )
        context["orphan_values"] = self._orphan_values(
            current_event.pk, requirements=prepared.requirements, session=session
        )
        context["fields_url"] = (
            reverse("panel:proposal-create-fields", kwargs={"slug": current_event.slug})
            if session is None
            else reverse(
                "panel:proposal-edit-fields",
                kwargs={"slug": current_event.slug, "proposal_id": session.pk},
            )
        )

    def _orphan_values(
        self,
        event_pk: int,
        *,
        requirements: Sequence[SessionFieldRequirementDTO],
        session: SessionDTO | None,
    ) -> list[OrphanFieldValue]:
        # A session being created has no stored answers, so it can never have
        # any outside its category.
        if session is None:
            return []
        asked_pks = {req.field.pk for req in requirements}
        fields_by_pk = {
            f.pk: f for f in self.request.di.uow.session_fields.list_by_event(event_pk)
        }
        return [
            OrphanFieldValue(
                field_id=value.field_id,
                name=value.field_question or value.field_name,
                display_value=_display_field_value(
                    fields_by_pk.get(value.field_id), value
                ),
            )
            for value in self.request.di.uow.sessions.read_field_values(session.pk)
            if value.field_id not in asked_pks
        ]

    def _collect_ids(
        self, *, plural: str, singular: str, valid: set[int]
    ) -> list[int] | None:
        # The hidden sentinel separates "this picker wasn't on the page" (leave
        # the stored selection alone) from "submitted with nothing ticked".
        if self.request.POST.get(f"{plural}_submitted") != "1":
            return None
        raw_ids = self.request.POST.getlist(f"{singular}_ids")
        return list({int(i) for i in raw_ids if i.isdigit()} & valid)

    def _picker_context(
        self,
        context: dict[str, Any],
        *,
        plural: str,
        singular: str,
        all_items: Sequence[_HasPk],
        stored: Iterable[int],
    ) -> None:
        valid = {item.pk for item in all_items}
        submitted = self._collect_ids(plural=plural, singular=singular, valid=valid)
        context[f"all_{plural}"] = all_items
        # An in-progress (re-submitted) selection wins over the stored values so
        # it survives an invalid re-render; both are constrained to valid pks.
        context[f"assigned_{singular}_pks"] = (
            set(submitted) if submitted is not None else set(stored) & valid
        )

    def _collect_track_ids(self, event_pk: int) -> list[int] | None:
        tracks = self.request.di.uow.tracks.list_by_event(event_pk)
        return self._collect_ids(
            plural="tracks", singular="track", valid={t.pk for t in tracks}
        )

    def _collect_time_slot_ids(self, event_pk: int) -> list[int] | None:
        slots = self.request.di.uow.time_slots.list_by_event(event_pk)
        return self._collect_ids(
            plural="time_slots", singular="time_slot", valid={s.pk for s in slots}
        )

    def _collect_facilitator_ids(self, event_pk: int) -> list[int] | None:
        facilitators = self.request.di.uow.facilitators.list_by_event(event_pk)
        return self._collect_ids(
            plural="facilitators",
            singular="facilitator",
            valid={f.pk for f in facilitators},
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

    def _collect_remove_field_ids(
        self,
        event_pk: int,
        *,
        requirements: Sequence[SessionFieldRequirementDTO],
        session: SessionDTO,
    ) -> list[int]:
        raw_ids = self.request.POST.getlist("remove_field_ids")
        submitted = {int(fid) for fid in raw_ids if fid.isdigit()}
        # Only answers the category no longer asks for may be removed here; the
        # rest are edited through their own inputs.
        orphan_pks = {
            orphan.field_id
            for orphan in self._orphan_values(
                event_pk, requirements=requirements, session=session
            )
        }
        return list(submitted & orphan_pks)

    def _render(self, context: dict[str, Any], prepared: _Prepared) -> HttpResponse:
        event_pk = context["current_event"].pk
        session = prepared.session
        proposal_id = session.pk if session else None
        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["form"] = prepared.form

        sessions = self.request.di.uow.sessions
        self._picker_context(
            context,
            plural="facilitators",
            singular="facilitator",
            all_items=self.request.di.uow.facilitators.list_by_event(event_pk),
            stored=(
                (f.pk for f in sessions.read_facilitators(proposal_id))
                if proposal_id is not None
                else ()
            ),
        )
        self._picker_context(
            context,
            plural="tracks",
            singular="track",
            all_items=self.request.di.uow.tracks.list_by_event(event_pk),
            stored=(
                sessions.read_track_ids(proposal_id) if proposal_id is not None else ()
            ),
        )
        self._picker_context(
            context,
            plural="time_slots",
            singular="time_slot",
            all_items=self.request.di.uow.time_slots.list_by_event(event_pk),
            stored=(
                sessions.read_preferred_time_slot_ids(proposal_id)
                if proposal_id is not None
                else ()
            ),
        )

        self._add_field_context(context, prepared)
        context["facilitator_personal_data"] = (
            self._personal_data_for_render(event_pk, session.pk)
            if session is not None
            else []
        )
        return TemplateResponse(self.request, "panel/proposal-form.html", context)

    def _personal_data_for_render(
        self, event_pk: int, proposal_id: int
    ) -> FacilitatorPersonalData:
        if self.request.POST.get("personal_data_submitted") == "1":
            return self._get_facilitator_personal_data_post(event_pk, proposal_id)
        return self._get_facilitator_personal_data(event_pk, proposal_id)

    def get(
        self, _request: PanelRequest, slug: str, proposal_id: int | None = None
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        prepared = self._prepare(slug, current_event, proposal_id)
        if isinstance(prepared, HttpResponse):
            return prepared

        return self._render(context, prepared)

    def post(
        self, _request: PanelRequest, slug: str, proposal_id: int | None = None
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        prepared = self._prepare(slug, current_event, proposal_id, self.request.POST)
        if isinstance(prepared, HttpResponse):
            return prepared

        if (session := prepared.session) is None:
            return self._create(context, current_event=current_event, prepared=prepared)
        return self._update(
            context, current_event=current_event, session=session, prepared=prepared
        )

    def _create(
        self, context: dict[str, Any], *, current_event: EventDTO, prepared: _Prepared
    ) -> HttpResponse:
        form = prepared.form
        # Invariant: a hand-added proposal always has at least one facilitator.
        # The picker is not a form field, so the rule is enforced here and
        # reported through the form's own error channel.
        facilitator_ids = self._collect_facilitator_ids(current_event.pk) or []
        if not form.is_valid() or not facilitator_ids:
            if not facilitator_ids:
                form.add_error(None, _("Please select at least one facilitator."))
            return self._render(context, prepared)

        try:
            proposal_id = self._write_new_session(
                current_event=current_event,
                requirements=prepared.requirements,
                form=form,
                facilitator_ids=facilitator_ids,
            )
        except DatabaseConstraintError:
            messages.error(
                self.request,
                _("Couldn't save the session. Please check your input and try again."),
            )
            return self._render(context, prepared)
        messages.success(self.request, _("Proposal created successfully."))
        return redirect(
            "panel:proposal-detail", slug=current_event.slug, proposal_id=proposal_id
        )

    def _write_new_session(
        self,
        *,
        current_event: EventDTO,
        requirements: Sequence[SessionFieldRequirementDTO],
        form: forms.Form,
        facilitator_ids: list[int],
    ) -> int:
        title = form.cleaned_data["title"]
        session_slug = make_unique_slug(
            name=title,
            default="session",
            check_exists=lambda s: self.request.di.uow.sessions.slug_exists(
                current_event.pk, s
            ),
        )
        track_ids = self._collect_track_ids(current_event.pk)
        time_slot_ids = self._collect_time_slot_ids(current_event.pk)
        with self.request.di.uow.savepoint():
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
            if requirements:
                self.request.di.uow.sessions.save_field_values(
                    proposal_id,
                    collect_session_field_values(
                        session_id=proposal_id, requirements=requirements, form=form
                    ),
                )
            if track_ids:
                self.request.di.uow.sessions.set_session_tracks(proposal_id, track_ids)
            if time_slot_ids:
                self.request.di.uow.sessions.set_time_slots(proposal_id, time_slot_ids)
        return proposal_id

    def _update(
        self,
        context: dict[str, Any],
        *,
        current_event: EventDTO,
        session: SessionDTO,
        prepared: _Prepared,
    ) -> HttpResponse:
        form = prepared.form
        if not form.is_valid():
            return self._render(context, prepared)

        try:
            self._write_content_edit(
                current_event=current_event,
                session=session,
                form=form,
                requirements=prepared.requirements,
            )
        except DatabaseConstraintError:
            messages.error(
                self.request,
                _("Couldn't save your changes. Please check your input and try again."),
            )
            return self._render(context, prepared)

        messages.success(self.request, _("Proposal updated successfully."))
        return redirect(
            "panel:proposal-detail", slug=current_event.slug, proposal_id=session.pk
        )

    def _write_content_edit(
        self,
        *,
        current_event: EventDTO,
        session: SessionDTO,
        form: forms.Form,
        requirements: Sequence[SessionFieldRequirementDTO],
    ) -> None:
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
        remove_field_ids = self._collect_remove_field_ids(
            current_event.pk, requirements=requirements, session=session
        )
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

            new_limit = form.cleaned_data.get("participants_limit") or 0
            if new_limit == 0 or new_limit > session.participants_limit:
                self.request.services.waitlist_promotion.fill_freed_seats(
                    session_id=session.pk
                )


class ProposalFormFieldsComponentView(ProposalFormPageView):
    """Re-render the form's session fields for the picked category."""

    http_method_names = ("get",)

    def get(
        self, _request: PanelRequest, slug: str, proposal_id: int | None = None
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        prepared = self._prepare(slug, current_event, proposal_id)
        if isinstance(prepared, HttpResponse):
            return prepared

        self._add_field_context(context, prepared)
        context["form"] = prepared.form
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

        back = self._redirect_target(slug)
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

    def _redirect_target(self, slug: str) -> str:
        next_url = self.request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={self.request.get_host()}
        ):
            return next_url
        return reverse("panel:proposals", kwargs={"slug": slug})

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
