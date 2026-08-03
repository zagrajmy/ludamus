"""Facilitator views (list, detail, create, edit, merge)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    build_column_values,
    facilitator_tab_urls,
    make_unique_slug,
)
from ludamus.gates.web.django.dynamic_fields import (
    answered_value,
    dynamic_fields_form,
    field_descriptors,
)
from ludamus.gates.web.django.forms import (
    ACCREDITATION_TYPE_LABELS,
    FacilitatorEditForm,
    FacilitatorForm,
)
from ludamus.mills import FacilitatorMergeService
from ludamus.pacts import (
    FacilitatorData,
    FacilitatorMergeError,
    FacilitatorUpdateData,
    NotFoundError,
    PersonalDataFieldValueData,
)
from ludamus.pacts.submissions import (
    AccreditationType,
    FacilitatorActionError,
    FacilitatorListQuery,
    OrganizerActionRefusal,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django import forms
    from django.http import HttpResponse, QueryDict
    from django.utils.functional import _StrPromise

    from ludamus.pacts import FieldDescriptor, FieldValue, OrganizerFieldDTO
    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.submissions import FacilitatorListContextDTO


_FACILITATORS_PAGE_SIZE = 50  # ponytail: revisit after dogfooding
# A tampered `?organizer=` value falls back to "all", so the toolbar never
# shows a selected option the list is not actually filtered by.
_ORGANIZER_FILTERS = ("mine", "unassigned")
# Why the claim or the step-down did not apply. A double-click and a genuine
# clash are different stories, so they get different messages.
_ORGANIZER_REFUSALS: dict[OrganizerActionRefusal, _StrPromise] = {
    OrganizerActionRefusal.ALREADY_TAKEN: gettext_lazy(
        "Someone else already handles this facilitator."
    ),
    OrganizerActionRefusal.ALREADY_YOURS: gettext_lazy(
        "You already handle this facilitator."
    ),
    OrganizerActionRefusal.ALREADY_FREE: gettext_lazy(
        "Nobody handles this facilitator."
    ),
    OrganizerActionRefusal.NOT_ORGANIZER: gettext_lazy(
        "Only the person handling this facilitator can step down."
    ),
}


_PERSONAL_PREFIX = "personal"


def _personal_fields_form(
    *,
    fields: Sequence[OrganizerFieldDTO],
    data: QueryDict | None = None,
    values: Mapping[str, FieldValue] | None = None,
) -> forms.Form:
    # The panel records answers on someone's behalf, so nothing is required
    # here even when the proposal wizard would demand it.
    return dynamic_fields_form(
        prefix=_PERSONAL_PREFIX,
        fields=[(field, False) for field in fields],
        data=data,
        initial=values or {},
    )


def _personal_descriptors(
    fields: Sequence[OrganizerFieldDTO], form: forms.Form
) -> list[FieldDescriptor]:
    return field_descriptors(
        prefix=_PERSONAL_PREFIX, fields=[(field, False) for field in fields], form=form
    )


def _personal_entries(
    *,
    form: forms.Form,
    fields: Sequence[OrganizerFieldDTO],
    facilitator_id: int,
    event_id: int,
) -> list[PersonalDataFieldValueData]:
    return [
        PersonalDataFieldValueData(
            facilitator_id=facilitator_id,
            event_id=event_id,
            field_id=field.pk,
            value=answered_value(prefix=_PERSONAL_PREFIX, field_def=field, form=form),
        )
        for field in fields
    ]


def _read_user(request: PanelRequest, user_id: int | None) -> UserDTO | None:
    if user_id is None:
        return None
    try:
        return request.di.uow.active_users.read_by_id(user_id)
    except NotFoundError:
        return None


class FacilitatorsPageView(PanelAccessMixin, EventContextMixin, View):
    """List facilitators for an event."""

    request: PanelRequest

    def _read_query(self) -> FacilitatorListQuery:
        accreditation = self.request.GET.get("accreditation", "").strip()
        organizer = self.request.GET.get("organizer", "").strip()
        return FacilitatorListQuery(
            search=self.request.GET.get("search", "").strip(),
            accreditation=(accreditation if accreditation in AccreditationType else ""),
            flagged=self.request.GET.get("flagged") == "true",
            organizer=(organizer if organizer in _ORGANIZER_FILTERS else ""),
            current_user_id=self.request.context.current_user_id,
            sort=self.request.GET.get("sort", "").strip() or "name",
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

        query = self._read_query()
        list_context = self.request.services.facilitator_panel.list_context(
            event_id=current_event.pk, query=query
        )
        page_obj = Paginator(
            list_context.facilitators, _FACILITATORS_PAGE_SIZE
        ).get_page(self.request.GET.get("page"))

        column_values = build_column_values(
            panel=self.request.services.facilitator_panel,
            facilitators=list(page_obj.object_list),
            columns=list_context.columns,
        )

        context["active_nav"] = "facilitators"
        context["active_tab"] = "list"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["facilitators"] = list(page_obj.object_list)
        context["page_obj"] = page_obj
        context["columns"] = list_context.columns
        context["column_values"] = column_values
        context["filterable_fields"] = list_context.filterable_fields
        context["filter_fields"] = {
            field.pk: query.raw_field_filters.get(field.pk, "")
            for field in list_context.filterable_fields
        }
        context["filter_search"] = query.search
        context["filter_accreditation"] = query.accreditation or None
        context["filter_flagged"] = query.flagged
        context["filter_organizer"] = query.organizer
        context["filter_sort"] = query.sort
        context["filters_active"] = bool(
            query.search
            or query.accreditation
            or query.flagged
            or query.organizer
            or list_context.field_filters
        )
        context["accreditation_types"] = [
            (t.value, ACCREDITATION_TYPE_LABELS[t]) for t in AccreditationType
        ]
        return TemplateResponse(self.request, "panel/facilitators.html", context)


class FacilitatorDetailPageView(PanelAccessMixin, EventContextMixin, View):
    """View facilitator details and personal data."""

    request: PanelRequest

    def get(
        self, _request: PanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            facilitator = self.request.di.uow.facilitators.read_by_event_and_slug(
                current_event.pk, facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        personal_data_fields = self.request.di.uow.personal_data_fields.list_by_event(
            current_event.pk
        )
        personal_data_values = (
            self.request.di.uow.personal_data_field_values.read_for_facilitator_event(
                facilitator.pk, current_event.pk
            )
        )
        personal_data_items = [
            (field, personal_data_values.get(field.slug))
            for field in personal_data_fields
        ]

        has_personal_data = any(v for _, v in personal_data_items)

        context["active_nav"] = "facilitators"
        context["facilitator"] = facilitator
        context["linked_user"] = _read_user(self.request, facilitator.user_id)
        context["accreditation_type_display"] = ACCREDITATION_TYPE_LABELS[
            AccreditationType(facilitator.accreditation_type)
        ]
        context["personal_data_items"] = personal_data_items
        context["has_personal_data"] = has_personal_data
        context["sessions"] = self.request.di.uow.sessions.list_by_facilitator(
            facilitator.pk
        )
        return TemplateResponse(self.request, "panel/facilitator-detail.html", context)


class FacilitatorCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new facilitator for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        fields = self.request.di.uow.personal_data_fields.list_by_event(
            current_event.pk
        )
        context["active_nav"] = "facilitators"
        context["form"] = FacilitatorForm()
        context["field_descriptors"] = _personal_descriptors(
            fields, _personal_fields_form(fields=fields)
        )
        return TemplateResponse(self.request, "panel/facilitator-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        fields = self.request.di.uow.personal_data_fields.list_by_event(
            current_event.pk
        )
        form = FacilitatorForm(self.request.POST)
        fields_form = _personal_fields_form(fields=fields, data=self.request.POST)
        if not form.is_valid() or not fields_form.is_valid():
            context["active_nav"] = "facilitators"
            context["form"] = form
            context["field_descriptors"] = _personal_descriptors(fields, fields_form)
            return TemplateResponse(
                self.request, "panel/facilitator-create.html", context
            )

        display_name = form.cleaned_data["display_name"]
        facilitator_slug = make_unique_slug(
            name=display_name,
            default="facilitator",
            check_exists=lambda s: self.request.di.uow.facilitators.slug_exists(
                current_event.pk, s
            ),
        )
        facilitator = self.request.di.uow.facilitators.create(
            FacilitatorData(
                accreditation_type=form.cleaned_data["accreditation_type"],
                display_name=display_name,
                event_id=current_event.pk,
                organizer_id=(
                    self.request.context.current_user_id
                    if form.cleaned_data["assign_me"]
                    else None
                ),
                slug=facilitator_slug,
                user_id=None,
            )
        )
        entries = _personal_entries(
            form=fields_form,
            fields=fields,
            facilitator_id=facilitator.pk,
            event_id=current_event.pk,
        )
        if entries:
            self.request.services.personal_data_field_values.update_personal_data(
                event_id=current_event.pk,
                facilitator_id=facilitator.pk,
                entries=entries,
                user_id=self.request.context.current_user_id,
            )
        messages.success(self.request, _("Facilitator created successfully."))
        return redirect("panel:facilitators", slug=slug)


class FacilitatorEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing facilitator."""

    request: PanelRequest

    def _stored_fields_form(
        self, event_pk: int, facilitator_pk: int
    ) -> tuple[Sequence[OrganizerFieldDTO], forms.Form]:
        fields = self.request.di.uow.personal_data_fields.list_by_event(event_pk)
        values = (
            self.request.di.uow.personal_data_field_values.read_for_facilitator_event(
                facilitator_pk, event_pk
            )
        )
        return fields, _personal_fields_form(fields=fields, values=values)

    def get(
        self, _request: PanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            facilitator = self.request.di.uow.facilitators.read_by_event_and_slug(
                current_event.pk, facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        fields, fields_form = self._stored_fields_form(current_event.pk, facilitator.pk)
        context["active_nav"] = "facilitators"
        context["facilitator"] = facilitator
        context["form"] = FacilitatorEditForm(
            initial={
                "accreditation_type": facilitator.accreditation_type,
                "internal_comment": facilitator.internal_comment,
            }
        )
        context["field_descriptors"] = _personal_descriptors(fields, fields_form)
        return TemplateResponse(self.request, "panel/facilitator-edit.html", context)

    def post(
        self, _request: PanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            facilitator = self.request.di.uow.facilitators.read_by_event_and_slug(
                current_event.pk, facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        form = FacilitatorEditForm(self.request.POST)
        all_personal_fields = self.request.di.uow.personal_data_fields.list_by_event(
            current_event.pk
        )
        fields_form = _personal_fields_form(
            fields=all_personal_fields, data=self.request.POST
        )
        if not form.is_valid() or not fields_form.is_valid():
            context["active_nav"] = "facilitators"
            context["facilitator"] = facilitator
            context["form"] = form
            context["field_descriptors"] = _personal_descriptors(
                all_personal_fields, fields_form
            )
            return TemplateResponse(
                self.request, "panel/facilitator-edit.html", context
            )

        entries = _personal_entries(
            form=fields_form,
            fields=all_personal_fields,
            facilitator_id=facilitator.pk,
            event_id=current_event.pk,
        )
        self.request.services.personal_data_field_values.update_facilitator(
            event_id=current_event.pk,
            facilitator_id=facilitator.pk,
            data=FacilitatorUpdateData(
                accreditation_type=form.cleaned_data["accreditation_type"],
                internal_comment=form.cleaned_data["internal_comment"],
            ),
            entries=entries,
            user_id=self.request.context.current_user_id,
        )

        messages.success(self.request, _("Facilitator updated successfully."))
        return redirect(
            "panel:facilitator-detail", slug=slug, facilitator_slug=facilitator_slug
        )


class FacilitatorMergePageView(PanelAccessMixin, EventContextMixin, View):
    """Merge multiple facilitators into one."""

    request: PanelRequest

    def _list_context(self, event_id: int) -> FacilitatorListContextDTO:
        return self.request.services.facilitator_panel.list_context(
            event_id=event_id, query=FacilitatorListQuery()
        )

    def _render(
        self,
        *,
        context: dict[str, object],
        slug: str,
        list_context: FacilitatorListContextDTO,
        preselected_ids: set[int],
        error: str | None,
    ) -> HttpResponse:
        context["active_nav"] = "facilitators"
        context["active_tab"] = "merge"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["facilitators"] = list_context.facilitators
        context["columns"] = list_context.columns
        context["column_values"] = build_column_values(
            panel=self.request.services.facilitator_panel,
            facilitators=list_context.facilitators,
            columns=list_context.columns,
        )
        context["preselected_ids"] = preselected_ids
        context["error"] = error
        return TemplateResponse(self.request, "panel/facilitator-merge.html", context)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        raw_ids = self.request.GET.getlist("ids")
        return self._render(
            context=context,
            slug=slug,
            list_context=self._list_context(current_event.pk),
            preselected_ids={int(fid) for fid in raw_ids if fid.isdigit()},
            error=None,
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        list_context = self._list_context(current_event.pk)
        valid_pks = {f.pk for f in list_context.facilitators}
        raw_selected = self.request.POST.getlist("facilitator_ids")
        selected_ids = [
            n for fid in raw_selected if fid.isdigit() and (n := int(fid)) in valid_pks
        ]
        raw_target = self.request.POST.get("target_id", "")
        target_id = (
            int(raw_target)
            if raw_target.isdigit() and int(raw_target) in valid_pks
            else None
        )

        min_required = 2
        if len(selected_ids) < min_required or target_id not in selected_ids:
            return self._render(
                context=context,
                slug=slug,
                list_context=list_context,
                preselected_ids=set(selected_ids),
                error=_("Select at least two facilitators and choose a merge target."),
            )

        source_ids = [fid for fid in selected_ids if fid != target_id]
        try:
            FacilitatorMergeService(self.request.di.uow).merge(target_id, source_ids)
        except FacilitatorMergeError:
            return self._render(
                context=context,
                slug=slug,
                list_context=list_context,
                preselected_ids=set(selected_ids),
                error=_(
                    "Cannot merge facilitators that each have a linked user account."
                ),
            )

        messages.success(self.request, _("Facilitators merged successfully."))
        return redirect("panel:facilitators", slug=slug)


class _FacilitatorActionView(PanelAccessMixin, EventContextMixin, View):
    """Shared POST handler for single-facilitator triage actions."""

    request: PanelRequest
    http_method_names = ("post",)
    success_message: str | _StrPromise = ""

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        raise NotImplementedError

    def post(
        self, _request: PanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            self._apply(current_event.pk, facilitator_slug)
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)
        except FacilitatorActionError as exc:
            messages.error(self.request, _ORGANIZER_REFUSALS[exc.refusal])
            return redirect(self._safe_next(slug))

        messages.success(self.request, self.success_message)
        return redirect(self._safe_next(slug))

    def _safe_next(self, slug: str) -> str:
        next_url = self.request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("panel:facilitators", kwargs={"slug": slug})


class FacilitatorFlagActionView(_FacilitatorActionView):
    """Flag a facilitator for deletion (POST only)."""

    success_message = gettext_lazy("Facilitator flagged for deletion.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.set_flag(
            event_id=event_id, facilitator_slug=facilitator_slug, flagged=True
        )


class FacilitatorUnflagActionView(_FacilitatorActionView):
    """Clear a facilitator's deletion flag (POST only)."""

    success_message = gettext_lazy("Facilitator unflagged.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.set_flag(
            event_id=event_id, facilitator_slug=facilitator_slug, flagged=False
        )


class FacilitatorMarkGuestActionView(_FacilitatorActionView):
    """Set a facilitator's accreditation to guest (POST only)."""

    success_message = gettext_lazy("Facilitator marked as guest.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.set_accreditation(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            accreditation_type=AccreditationType.GUEST.value,
            user_id=self.request.context.current_user_id,
        )


class FacilitatorAssignOrganizerActionView(_FacilitatorActionView):
    """Take an unassigned facilitator on as its organizer (POST only)."""

    success_message = gettext_lazy("You now handle this facilitator.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.assign_organizer(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            organizer_id=self.request.context.current_user_id,
        )


class FacilitatorUnassignOrganizerActionView(_FacilitatorActionView):
    """Release a facilitator you organize, so someone else can take it."""

    success_message = gettext_lazy("Stepped down.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.unassign_organizer(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            organizer_id=self.request.context.current_user_id,
            force=self.request.user.is_superuser,
        )


class FacilitatorColumnsPageView(PanelAccessMixin, EventContextMixin, View):
    """Choose which personal-data fields show as columns on the list."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        columns = self.request.services.facilitator_panel.columns_context(
            current_event.pk
        )
        context["active_nav"] = "facilitators"
        context["active_tab"] = "columns"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["chosen_columns"] = columns.chosen
        context["available_columns"] = columns.available
        return TemplateResponse(self.request, "panel/facilitator-columns.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        # The chosen keys arrive in display order; the service drops anything
        # that isn't this event's own column.
        self.request.services.facilitator_panel.set_columns(
            event_id=current_event.pk, columns=self.request.POST.getlist("columns")
        )
        messages.success(self.request, _("Columns updated."))
        return redirect("panel:facilitators", slug=slug)
