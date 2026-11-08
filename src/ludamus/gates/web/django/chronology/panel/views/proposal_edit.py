"""The proposal form — one page and one fields fragment, create and edit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.dynamic_fields import (
    answered_value,
    field_descriptors,
    fold_custom_answers,
    requirement_fields,
    unfold_custom_answers,
)
from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelMixin,
    PanelContext,
    back_to_proposals,
    format_field_value,
    proposal_detail_url,
)
from ludamus.gates.web.django.event.panel.views.facilitator_fields import (
    personal_descriptors,
    personal_fields_form,
)
from ludamus.gates.web.django.forms import (
    CUSTOM_DURATION,
    SessionEditForm,
    create_proposal_form,
)
from ludamus.gates.web.django.redirects import RedirectError
from ludamus.gates.web.django.request_ids import parse_id, parse_ids
from ludamus.pacts.durations import parse_duration
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.fields import PersonalDataFieldValueData, SessionFieldValueData
from ludamus.pacts.images import parse_uploaded_file, stored_file
from ludamus.pacts.panel import ProposalDraft, ProposalEdit
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.sessions import SessionContentEditData, SessionData, SessionStatus

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from django import forms
    from django.http import HttpResponse, QueryDict

    from ludamus.gates.web.django.panel import PanelRequest
    from ludamus.pacts.facilitators import FacilitatorDTO
    from ludamus.pacts.fields import FieldDescriptor, OrganizerFieldDTO
    from ludamus.pacts.panel import ProposalFormDTO, ProposalFormFieldsDTO
    from ludamus.pacts.proposal_categories import (
        ProposalCategoryDTO,
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


class _HasPk(Protocol):
    # The three checkbox pickers hold unrelated DTOs; all the shared code needs
    # from them is a pk.
    pk: int


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


def collect_session_field_inputs(
    *, requirements: Sequence[SessionFieldRequirementDTO], form: forms.Form
) -> dict[int, str | list[str] | bool]:
    # Only the category's own fields are read back; a value the category no
    # longer asks for is left untouched rather than blanked. Blanks are kept
    # in the result — on an edit they blank an answer that exists, and the
    # write path is what drops the ones that would create an empty row.
    folded = fold_custom_answers(
        cleaned=form.cleaned_data,
        fields=[req.field for req in requirements],
        prefix="session",
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


def _orphan_values(fields: ProposalFormFieldsDTO) -> list[OrphanFieldValue]:
    # A session being created has no stored answers, so it can never have any
    # outside its category.
    asked_pks = {req.field.pk for req in fields.requirements}
    fields_by_pk = {f.pk: f for f in fields.session_fields}
    return [
        OrphanFieldValue(
            field_id=value.field_id,
            name=value.field_question or value.field_name,
            display_value=format_field_value(
                value=value.value,
                labels=_option_labels(fields_by_pk.get(value.field_id)),
            ),
        )
        for value in fields.field_values
        if value.field_id not in asked_pks
    ]


# The personal-data blocks are separate forms, so their errors never reach the
# page's error summary on their own — this says why the save didn't happen.
PERSONAL_DATA_ERROR = gettext_lazy(
    "Fix the facilitator personal data below before saving."
)


class _ProposalFormBase(EventPanelMixin, View):
    """Request-scoped pieces the full page and the fields fragment both need."""

    request: PanelRequest

    def _requested_category_id(self) -> int | None:
        # A submitted or HTMX-swapped category picks the fields to render.
        data = self.request.POST if self.request.method == "POST" else self.request.GET
        return parse_id(data.get("category_id"))

    def _proposal_not_found(self) -> RedirectError:
        return RedirectError(
            reverse("panel:proposals", kwargs={"slug": self.current_event.slug}),
            error=_("Proposal not found."),
        )

    def _build_form(
        self, fields: ProposalFormFieldsDTO, data: QueryDict | None
    ) -> SessionEditForm:
        category = fields.category
        form_class = create_proposal_form(
            [(c.pk, c.name) for c in fields.categories],
            requirements=fields.requirements,
            durations=category.durations if category else (),
        )
        if data is not None:
            return form_class(data, self.request.FILES)
        if (session := fields.proposal) is None:
            # Preselect the resolved category so the picker agrees with the
            # fields rendered beneath it.
            return form_class(
                initial={"category_id": category.pk} if category else None
            )
        duration = _duration_initial(session.duration, category)
        initial: dict[str, Any] = {
            "title": session.title,
            "facilitator_name": session.facilitator_name,
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
        stored = {fv.field_id: fv.value for fv in fields.field_values}
        initial |= unfold_custom_answers(
            stored={
                f"session_{req.field.slug}": stored[req.field.pk]
                for req in fields.requirements
                if req.field.pk in stored
            },
            fields=[req.field for req in fields.requirements],
            prefix="session",
        )
        return form_class(initial=initial)

    def _field_context(
        self, fields: ProposalFormFieldsDTO, form: forms.Form
    ) -> dict[str, Any]:
        # The session-fields fieldset, whether it renders inside the page or on
        # its own after a category swap.
        slug = self.current_event.slug
        session = fields.proposal
        return {
            "field_descriptors": field_descriptors(
                prefix="session",
                fields=requirement_fields(fields.requirements),
                form=form,
            ),
            "orphan_values": _orphan_values(fields),
            "fields_url": (
                reverse("panel:proposal-create-fields", kwargs={"slug": slug})
                if session is None
                else reverse(
                    "panel:proposal-edit-fields",
                    kwargs={"slug": slug, "proposal_id": session.pk},
                )
            ),
        }


class ProposalFormPageView(_ProposalFormBase):
    """Create a new proposal or edit an existing one from the organizer panel."""

    def _page(self, proposal_id: int | None) -> ProposalFormDTO:
        # None proposal_id is the create flow; otherwise the service scopes the
        # id to this event, so a foreign one is NotFound before anything reads
        # or writes it.
        try:
            return self.request.services.proposal_page.form(
                event_id=self.current_event.pk,
                proposal_id=proposal_id,
                category_id=self._requested_category_id(),
            )
        except NotFoundError:
            raise self._proposal_not_found() from None

    def _collect_ids(
        self, *, plural: str, singular: str, valid: Iterable[_HasPk]
    ) -> list[int] | None:
        # The hidden sentinel separates "this picker wasn't on the page" (leave
        # the stored selection alone) from "submitted with nothing ticked". Ids
        # the event doesn't own are dropped rather than written.
        if self.request.POST.get(f"{plural}_submitted") != "1":
            return None
        submitted = set(parse_ids(self.request.POST.getlist(f"{singular}_ids")))
        return list(submitted & {item.pk for item in valid})

    def _picker_context(
        self,
        context: PanelContext,
        *,
        plural: str,
        singular: str,
        all_items: Sequence[_HasPk],
        stored: Iterable[int],
    ) -> None:
        valid = {item.pk for item in all_items}
        submitted = self._collect_ids(plural=plural, singular=singular, valid=all_items)
        context[f"all_{plural}"] = all_items
        # An in-progress (re-submitted) selection wins over the stored values so
        # it survives an invalid re-render; both are constrained to valid pks.
        context[f"assigned_{singular}_pks"] = (
            set(submitted) if submitted is not None else set(stored) & valid
        )

    def _personal_data(
        self, page: ProposalFormDTO
    ) -> tuple[FacilitatorPersonalData, dict[int, forms.Form]]:
        # Read once, before the edit can change the assignment, so a facilitator
        # unticked in the same save keeps the answer posted on their card. The
        # forms come back bound only for the cards this request posted.
        if not (fields := page.personal_data_fields):
            return [], {}
        posted_ids: set[int] = set()
        if self.request.POST.get("personal_data_submitted") == "1":
            posted_ids = set(
                parse_ids(self.request.POST.getlist("personal_data_facilitator_ids"))
            )
        cards: FacilitatorPersonalData = []
        bound: dict[int, forms.Form] = {}
        for facilitator in page.assigned.facilitators:
            prefix = _facilitator_prefix(facilitator.pk)
            # A posted card is bound, so the panel enforces the same choice and
            # length rules the wizard does.
            form = personal_fields_form(
                prefix=prefix,
                fields=fields,
                data=self.request.POST if facilitator.pk in posted_ids else None,
                values=page.personal_data_values.get(facilitator.pk, {}),
            )
            if form.is_bound:
                bound[facilitator.pk] = form
            cards.append(
                PersonalDataCard(
                    facilitator=facilitator,
                    descriptors=personal_descriptors(
                        prefix=prefix, fields=fields, form=form
                    ),
                    has_errors=form.is_bound and not form.is_valid(),
                )
            )
        return cards, bound

    def _collect_remove_field_ids(self, fields: ProposalFormFieldsDTO) -> list[int]:
        submitted = set(parse_ids(self.request.POST.getlist("remove_field_ids")))
        # Only answers the category no longer asks for may be removed here; the
        # rest are edited through their own inputs.
        orphan_pks = {orphan.field_id for orphan in _orphan_values(fields)}
        return list(submitted & orphan_pks)

    def _render(
        self,
        page: ProposalFormDTO,
        form: forms.Form,
        personal_data: FacilitatorPersonalData | None = None,
    ) -> HttpResponse:
        context = self.panel_context()
        slug = self.current_event.slug
        session = page.fields.proposal
        context["active_nav"] = "proposals"
        context["proposal"] = session
        context["form"] = form
        context["cancel_url"] = (
            proposal_detail_url(request=self.request, slug=slug, proposal_id=session.pk)
            if session is not None
            else back_to_proposals(self.request, slug)
        )
        self._picker_context(
            context,
            plural="facilitators",
            singular="facilitator",
            all_items=page.facilitators,
            stored=(f.pk for f in page.assigned.facilitators),
        )
        self._picker_context(
            context,
            plural="tracks",
            singular="track",
            all_items=page.tracks,
            stored=page.assigned.track_ids,
        )
        self._picker_context(
            context,
            plural="time_slots",
            singular="time_slot",
            all_items=page.time_slots,
            stored=page.assigned.time_slot_ids,
        )
        context.update(self._field_context(page.fields, form))
        context["facilitator_personal_data"] = personal_data or []
        return TemplateResponse(self.request, "panel/proposal-form.html", context)

    def get(
        self, _request: PanelRequest, proposal_id: int | None = None, **_kwargs: str
    ) -> HttpResponse:
        page = self._page(proposal_id)
        personal_data, _bound = self._personal_data(page)
        return self._render(page, self._build_form(page.fields, None), personal_data)

    def post(
        self, _request: PanelRequest, proposal_id: int | None = None, **_kwargs: str
    ) -> HttpResponse:
        page = self._page(proposal_id)
        form = self._build_form(page.fields, self.request.POST)
        if (session := page.fields.proposal) is None:
            return self._create(page, form)
        return self._update(page, form, session_id=session.pk)

    def _create(self, page: ProposalFormDTO, form: SessionEditForm) -> HttpResponse:
        # Create-time rule, not an invariant: a hand-added proposal starts with
        # at least one facilitator, but an edit may later remove them all. The
        # picker is not a form field, so the rule is enforced here and reported
        # through the form's own error channel.
        facilitator_ids = (
            self._collect_ids(
                plural="facilitators", singular="facilitator", valid=page.facilitators
            )
            or []
        )
        # No personal-data check here: a proposal that does not exist yet has no
        # facilitators to render cards for, so the create page never posts any.
        if not form.is_valid() or not facilitator_ids:
            if not facilitator_ids:
                form.add_error(None, _("Please select at least one facilitator."))
            return self._render(page, form)

        # A DB constraint/data error surfaces as an inline form error (input
        # preserved), not a bare 500 the user reads as a transient glitch.
        try:
            proposal_id = self._write_new_session(
                page=page, form=form, facilitator_ids=facilitator_ids
            )
        except DatabaseConstraintError:
            messages.error(
                self.request,
                _("Couldn't save the session. Please check your input and try again."),
            )
            return self._render(page, form)
        messages.success(self.request, _("Proposal created successfully."))
        return redirect(
            "panel:proposal-detail",
            slug=self.current_event.slug,
            proposal_id=proposal_id,
        )

    def _write_new_session(
        self,
        *,
        page: ProposalFormDTO,
        form: SessionEditForm,
        facilitator_ids: list[int],
    ) -> int:
        event_id = self.current_event.pk
        requirements = page.fields.requirements
        title = form.cleaned_data["title"]
        session_data = SessionData(
            category_id=int(form.cleaned_data["category_id"]),
            event_id=event_id,
            contact_email=form.cleaned_data.get("contact_email") or "",
            description=form.cleaned_data.get("description") or "",
            facilitator_name=form.cleaned_data["facilitator_name"],
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
            event_id=event_id,
            draft=ProposalDraft(
                data=session_data,
                facilitator_ids=facilitator_ids,
                field_values=(
                    collect_session_field_inputs(requirements=requirements, form=form)
                    if requirements
                    else {}
                ),
                track_ids=self._collect_ids(
                    plural="tracks", singular="track", valid=page.tracks
                )
                or [],
                time_slot_ids=self._collect_ids(
                    plural="time_slots", singular="time_slot", valid=page.time_slots
                )
                or [],
            ),
        )

    def _update(
        self, page: ProposalFormDTO, form: SessionEditForm, *, session_id: int
    ) -> HttpResponse:
        personal_data, personal_forms = self._personal_data(page)
        personal_data_valid = not any(card.has_errors for card in personal_data)
        if not form.is_valid() or not personal_data_valid:
            if not personal_data_valid:
                form.add_error(None, PERSONAL_DATA_ERROR)
            return self._render(page, form, personal_data)

        # A DB constraint/data error surfaces as an inline form error (input
        # preserved), not a bare 500 the user reads as a transient glitch.
        try:
            self.request.services.proposal_page.update(
                event_id=self.current_event.pk,
                proposal_id=session_id,
                user_id=self.request.context.current_user_id,
                edit=self._edit(
                    page,
                    session_id=session_id,
                    form=form,
                    personal_forms=personal_forms,
                ),
            )
        except DatabaseConstraintError:
            messages.error(
                self.request,
                _("Couldn't save your changes. Please check your input and try again."),
            )
            return self._render(page, form, personal_data)
        except NotFoundError:
            raise self._proposal_not_found() from None

        messages.success(self.request, _("Proposal updated successfully."))
        return redirect(
            proposal_detail_url(
                request=self.request,
                slug=self.current_event.slug,
                proposal_id=session_id,
            )
        )

    def _edit(
        self,
        page: ProposalFormDTO,
        *,
        session_id: int,
        form: SessionEditForm,
        personal_forms: dict[int, forms.Form],
    ) -> ProposalEdit:
        event_id = self.current_event.pk
        return ProposalEdit(
            content=SessionContentEditData(
                update=form.update_data(),
                field_values=collect_session_field_values(
                    session_id=session_id,
                    requirements=page.fields.requirements,
                    form=form,
                ),
                facilitator_ids=self._collect_ids(
                    plural="facilitators",
                    singular="facilitator",
                    valid=page.facilitators,
                ),
                track_ids=self._collect_ids(
                    plural="tracks", singular="track", valid=page.tracks
                ),
                time_slot_ids=self._collect_ids(
                    plural="time_slots", singular="time_slot", valid=page.time_slots
                ),
                remove_field_ids=self._collect_remove_field_ids(page.fields),
            ),
            personal_data={
                facilitator_id: [
                    PersonalDataFieldValueData(
                        facilitator_id=facilitator_id,
                        event_id=event_id,
                        field_id=field.pk,
                        value=answered_value(
                            prefix=_facilitator_prefix(facilitator_id),
                            field_def=field,
                            form=personal_form,
                        ),
                    )
                    for field in page.personal_data_fields
                ]
                for facilitator_id, personal_form in personal_forms.items()
            },
        )


class ProposalFormFieldsComponentView(_ProposalFormBase):
    """Re-render the form's session fields for the picked category."""

    http_method_names = ("get",)

    def get(
        self, _request: PanelRequest, proposal_id: int | None = None, **_kwargs: str
    ) -> HttpResponse:
        # A category swap re-renders one fieldset: it needs the event, not the
        # page's event list and stats.
        try:
            fields = self.request.services.proposal_page.form_fields(
                event_id=self.current_event.pk,
                proposal_id=proposal_id,
                category_id=self._requested_category_id(),
            )
        except NotFoundError:
            raise self._proposal_not_found() from None
        form = self._build_form(fields, None)
        context: dict[str, Any] = {
            "form": form,
            "category": fields.category,
            **self._field_context(fields, form),
        }
        return TemplateResponse(
            self.request, "panel/parts/proposal-session-fields.html", context
        )
