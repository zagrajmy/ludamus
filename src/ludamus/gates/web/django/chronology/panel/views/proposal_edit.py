# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""The proposal form — one page and one fields fragment, create and edit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    back_to_proposals,
    format_field_value,
    proposal_detail_url,
)
from ludamus.gates.web.django.dynamic_fields import (
    answered_value,
    dynamic_fields_form,
    field_descriptors,
    fold_custom_answers,
    requirement_fields,
    unfold_custom_answers,
)
from ludamus.gates.web.django.forms import CUSTOM_DURATION, create_proposal_form
from ludamus.pacts import (
    NotFoundError,
    PersonalDataFieldValueData,
    SessionContentEditData,
    SessionData,
    SessionFieldValueData,
    SessionStatus,
    SessionUpdateData,
)
from ludamus.pacts.durations import parse_duration
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import parse_uploaded_file, resolve_uploaded_file_field
from ludamus.pacts.panel import ProposalDraft
from ludamus.pacts.services import DatabaseConstraintError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from django import forms
    from django.http import QueryDict

    from ludamus.pacts import (
        EventDTO,
        FacilitatorDTO,
        FieldDescriptor,
        FieldValue,
        OrganizerFieldDTO,
        ProposalCategoryDTO,
        SessionDTO,
        SessionFieldRequirementDTO,
    )


@dataclass(frozen=True)
class PersonalDataCard:
    facilitator: FacilitatorDTO
    descriptors: list[FieldDescriptor]
    # A card is collapsed until it has something to say: the page opens the one
    # that is wrong rather than guessing from a page-wide error.
    has_errors: bool = False


FacilitatorPersonalData = list[PersonalDataCard]


def _facilitator_prefix(facilitator_id: int) -> str:
    return f"facilitator_{facilitator_id}_personal"


def _facilitator_fields_form(
    *,
    prefix: str,
    fields: Sequence[OrganizerFieldDTO],
    data: QueryDict | None = None,
    values: Mapping[str, FieldValue] | None = None,
) -> forms.Form:
    return dynamic_fields_form(
        prefix=prefix,
        fields=[(field, False) for field in fields],
        data=data,
        initial=values or {},
    )


def _descriptors(
    *, prefix: str, fields: Sequence[OrganizerFieldDTO], form: forms.Form
) -> list[FieldDescriptor]:
    return field_descriptors(
        prefix=prefix, fields=[(field, False) for field in fields], form=form
    )


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


def _option_labels(field: OrganizerFieldDTO | None) -> dict[str, str]:
    return {option.value: option.label for option in field.options} if field else {}


@dataclass(frozen=True)
class _DurationInitial:
    selected: str
    hours: int | None
    minutes: int | None


def _duration_initial(
    duration: str, category: ProposalCategoryDTO | None
) -> _DurationInitial:
    # A stored duration the category doesn't offer (imported, or set before the
    # category changed) still has to come back editable, so it preselects the
    # custom option with its hours and minutes filled in.
    presets = category.durations if category else []
    if duration and duration in presets:
        return _DurationInitial(selected=duration, hours=None, minutes=None)
    hours, minutes = parse_duration(duration)
    return _DurationInitial(
        selected=CUSTOM_DURATION if duration else "",
        hours=hours or None,
        minutes=minutes or None,
    )


def session_field_requirements(
    request: PanelRequest, category: ProposalCategoryDTO | None
) -> list[SessionFieldRequirementDTO]:
    if category is None:
        return []
    return request.di.uow.proposal_categories.list_session_field_requirements(
        category.pk
    )


def collect_session_field_inputs(
    *, requirements: Sequence[SessionFieldRequirementDTO], form: forms.Form
) -> dict[int, str | list[str] | bool]:
    # Only the category's own fields are read back; a value the category no
    # longer asks for is left untouched rather than blanked. Blanks are kept
    # in the result — on an edit they blank an answer that exists, and the
    # write path is what drops the ones that would create an empty row.
    folded = fold_custom_answers(
        cleaned=form.cleaned_data, requirements=requirements, prefix="session"
    )
    inputs: dict[int, str | list[str] | bool] = {}
    for req in requirements:
        value = folded.get(f"session_{req.field.slug}")
        inputs[req.field.pk] = value if isinstance(value, str | list | bool) else ""
    return inputs


def collect_session_field_values(
    *,
    session_id: int,
    requirements: Sequence[SessionFieldRequirementDTO],
    form: forms.Form,
) -> list[SessionFieldValueData]:
    return [
        SessionFieldValueData(session_id=session_id, field_id=field_id, value=value)
        for field_id, value in collect_session_field_inputs(
            requirements=requirements, form=form
        ).items()
    ]


# The personal-data blocks are separate forms, so their errors never reach the
# page's error summary on their own — this says why the save didn't happen.
PERSONAL_DATA_ERROR = gettext_lazy(
    "Fix the facilitator personal data below before saving."
)


class _ProposalFormBase(PanelAccessMixin, EventContextMixin, View):
    """Request-scoped pieces the full page and the fields fragment both need."""

    request: PanelRequest

    def _load_session(
        self, slug: str, current_event: EventDTO, proposal_id: int | None
    ) -> tuple[SessionDTO | None, HttpResponse | None]:
        # None proposal_id is the create flow; otherwise the service scopes the
        # id to this event, so a foreign one is NotFound before anything reads
        # or writes it.
        if proposal_id is None:
            return None, None
        try:
            session = self.request.services.proposal_panel.read_proposal(
                event_id=current_event.pk, proposal_id=proposal_id
            )
        except NotFoundError:
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
            durations=category.durations if category else (),
        )
        if data is not None:
            return form_class(data, self.request.FILES)
        if session is None:
            # Preselect the resolved category so the picker agrees with the
            # fields rendered beneath it.
            return form_class(
                initial={"category_id": category.pk} if category else None
            )
        duration = _duration_initial(session.duration, category)
        initial: dict[str, Any] = {
            "title": session.title,
            "display_name": session.display_name,
            "description": session.description,
            "contact_email": session.contact_email,
            "participants_limit": session.participants_limit,
            "min_age": session.min_age,
            "category_id": session.category_id,
            "cover_image": stored_file(
                session.cover_image_url, session.cover_image_original_name
            ),
            "duration": duration.selected,
            "duration_hours": duration.hours,
            "duration_minutes": duration.minutes,
        }
        stored = {
            fv.field_id: fv.value
            for fv in self.request.di.uow.sessions.read_field_values(session.pk)
        }
        initial |= unfold_custom_answers(
            stored={
                f"session_{req.field.slug}": stored[req.field.pk]
                for req in requirements
                if req.field.pk in stored
            },
            fields=[req.field for req in requirements],
            prefix="session",
        )
        return form_class(initial=initial)

    def _field_context(
        self, current_event: EventDTO, prepared: _Prepared
    ) -> dict[str, Any]:
        # The session-fields fieldset, whether it renders inside the page or on
        # its own after a category swap.
        session = prepared.session
        return {
            "field_descriptors": field_descriptors(
                prefix="session",
                fields=requirement_fields(prepared.requirements),
                form=prepared.form,
            ),
            "orphan_values": self._orphan_values(
                current_event.pk, requirements=prepared.requirements, session=session
            ),
            "fields_url": (
                reverse(
                    "panel:proposal-create-fields", kwargs={"slug": current_event.slug}
                )
                if session is None
                else reverse(
                    "panel:proposal-edit-fields",
                    kwargs={"slug": current_event.slug, "proposal_id": session.pk},
                )
            ),
        }

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
                display_value=format_field_value(
                    value=value.value,
                    labels=_option_labels(fields_by_pk.get(value.field_id)),
                ),
            )
            for value in self.request.di.uow.sessions.read_field_values(session.pk)
            if value.field_id not in asked_pks
        ]


class ProposalFormPageView(_ProposalFormBase):
    """Create a new proposal or edit an existing one from the organizer panel."""

    def _collect_ids(
        self, *, plural: str, singular: str, valid: set[int]
    ) -> list[int] | None:
        # The hidden sentinel separates "this picker wasn't on the page" (leave
        # the stored selection alone) from "submitted with nothing ticked". Ids
        # the event doesn't own are dropped rather than written.
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
        # One query for every assigned facilitator's answers instead of one
        # lookup per facilitator.
        values_by_facilitator = (
            self.request.di.uow.personal_data_field_values.list_values_for_facilitators(
                [f.pk for f in assigned], [f.pk for f in fields]
            )
        )
        result: FacilitatorPersonalData = []
        for facilitator in assigned:
            prefix = _facilitator_prefix(facilitator.pk)
            form = _facilitator_fields_form(
                prefix=prefix,
                fields=fields,
                values=values_by_facilitator.get(facilitator.pk, {}),
            )
            result.append(
                PersonalDataCard(
                    facilitator=facilitator,
                    descriptors=_descriptors(prefix=prefix, fields=fields, form=form),
                )
            )
        return result

    def _get_facilitator_personal_data_post(
        self, event_pk: int, proposal_id: int
    ) -> FacilitatorPersonalData:
        fields = self.request.di.uow.personal_data_fields.list_by_event(event_pk)
        if not fields:
            return []
        assigned = self.request.di.uow.sessions.read_facilitators(proposal_id)
        result: FacilitatorPersonalData = []
        for facilitator in assigned:
            prefix = _facilitator_prefix(facilitator.pk)
            form = _facilitator_fields_form(
                prefix=prefix, fields=fields, data=self.request.POST
            )
            result.append(
                PersonalDataCard(
                    facilitator=facilitator,
                    descriptors=_descriptors(prefix=prefix, fields=fields, form=form),
                    has_errors=not form.is_valid(),
                )
            )
        return result

    def _personal_data_forms(
        self, event_pk: int
    ) -> tuple[Sequence[OrganizerFieldDTO], dict[int, forms.Form]] | None:
        # One bound form per facilitator whose block was posted, so the panel
        # enforces the same choice and length rules the wizard does.
        if self.request.POST.get("personal_data_submitted") != "1":
            return None
        raw_ids = self.request.POST.getlist("personal_data_facilitator_ids")
        submitted_ids = {int(fid) for fid in raw_ids if fid.isdigit()}
        valid_pks = {
            f.pk for f in self.request.di.uow.facilitators.list_by_event(event_pk)
        }
        fields = self.request.di.uow.personal_data_fields.list_by_event(event_pk)
        return fields, {
            facilitator_id: _facilitator_fields_form(
                prefix=_facilitator_prefix(facilitator_id),
                fields=fields,
                data=self.request.POST,
            )
            for facilitator_id in submitted_ids & valid_pks
        }

    def _personal_data_is_valid(self, event_pk: int) -> bool:
        submitted = self._personal_data_forms(event_pk)
        return submitted is None or all(
            form.is_valid() for form in submitted[1].values()
        )

    def _collect_personal_data(
        self, event_pk: int
    ) -> dict[int, list[PersonalDataFieldValueData]] | None:
        if (submitted := self._personal_data_forms(event_pk)) is None:
            return None
        fields, posted = submitted
        return {
            facilitator_id: [
                PersonalDataFieldValueData(
                    facilitator_id=facilitator_id,
                    event_id=event_pk,
                    field_id=field.pk,
                    value=answered_value(
                        prefix=_facilitator_prefix(facilitator_id),
                        field_def=field,
                        form=form,
                    ),
                )
                for field in fields
            ]
            for facilitator_id, form in posted.items()
            # Validity is checked before the write; is_valid() here only
            # populates cleaned_data for the forms that passed.
            if form.is_valid()
        }

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
        current_event: EventDTO = context["current_event"]
        event_pk = current_event.pk
        session = prepared.session
        proposal_id = session.pk if session else None
        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["form"] = prepared.form
        context["cancel_url"] = (
            proposal_detail_url(
                request=self.request, slug=current_event.slug, proposal_id=proposal_id
            )
            if proposal_id is not None
            else back_to_proposals(self.request, current_event.slug)
        )

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

        context.update(self._field_context(current_event, prepared))
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
        # Create-time rule, not an invariant: a hand-added proposal starts with
        # at least one facilitator, but an edit may later remove them all. The
        # picker is not a form field, so the rule is enforced here and reported
        # through the form's own error channel.
        facilitator_ids = self._collect_facilitator_ids(current_event.pk) or []
        # No personal-data check here: a proposal that does not exist yet has no
        # facilitators to render cards for, so the create page never posts any.
        if not form.is_valid() or not facilitator_ids:
            if not facilitator_ids:
                form.add_error(None, _("Please select at least one facilitator."))
            return self._render(context, prepared)

        # A DB constraint/data error surfaces as an inline form error (input
        # preserved), not a bare 500 the user reads as a transient glitch.
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
        session_data = SessionData(
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
        )
        # A brand-new proposal has no stored cover to clear, so only an actual
        # upload is meaningful here.
        if cover := parse_uploaded_file(form.cleaned_data.get("cover_image")):
            session_data["cover_image"] = cover
        return self.request.services.proposal_panel.create_proposal(
            event_id=current_event.pk,
            draft=ProposalDraft(
                data=session_data,
                base_slug=slugify(title),
                facilitator_ids=facilitator_ids,
                field_values=(
                    collect_session_field_inputs(requirements=requirements, form=form)
                    if requirements
                    else {}
                ),
                track_ids=self._collect_track_ids(current_event.pk) or [],
                time_slot_ids=self._collect_time_slot_ids(current_event.pk) or [],
            ),
        )

    def _update(
        self,
        context: dict[str, Any],
        *,
        current_event: EventDTO,
        session: SessionDTO,
        prepared: _Prepared,
    ) -> HttpResponse:
        form = prepared.form
        personal_data_valid = self._personal_data_is_valid(current_event.pk)
        if not form.is_valid() or not personal_data_valid:
            if not personal_data_valid:
                form.add_error(None, PERSONAL_DATA_ERROR)
            return self._render(context, prepared)

        # A DB constraint/data error surfaces as an inline form error (input
        # preserved), not a bare 500 the user reads as a transient glitch.
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
            proposal_detail_url(
                request=self.request, slug=current_event.slug, proposal_id=session.pk
            )
        )

    def _write_content_edit(
        self,
        *,
        current_event: EventDTO,
        session: SessionDTO,
        form: forms.Form,
        requirements: Sequence[SessionFieldRequirementDTO],
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
        cover = resolve_uploaded_file_field(form.cleaned_data.get("cover_image"))
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
                    resize_agenda_item=True,
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

            # T2: a capacity change may have freed seats — promote waiters. An old
            # limit of 0 (unlimited → finite) also matches; fill_freed_seats recomputes.
            new_limit = form.cleaned_data.get("participants_limit") or 0
            if new_limit == 0 or new_limit > session.participants_limit:
                self.request.services.waitlist_promotion.fill_freed_seats(
                    session_id=session.pk
                )


class ProposalFormFieldsComponentView(_ProposalFormBase):
    """Re-render the form's session fields for the picked category."""

    http_method_names = ("get",)

    def get(
        self, _request: PanelRequest, slug: str, proposal_id: int | None = None
    ) -> HttpResponse:
        # A category swap re-renders one fieldset: it needs the event, not the
        # page's event list and stats.
        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")

        prepared = self._prepare(slug, current_event, proposal_id)
        if isinstance(prepared, HttpResponse):
            return prepared

        context: dict[str, Any] = {
            "form": prepared.form,
            "category": prepared.category,
            **self._field_context(current_event, prepared),
        }
        return TemplateResponse(
            self.request, "panel/parts/proposal-session-fields.html", context
        )
