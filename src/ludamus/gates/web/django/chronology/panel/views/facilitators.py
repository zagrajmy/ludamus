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
    facilitator_tab_urls,
    make_unique_slug,
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
from ludamus.pacts.submissions import AccreditationType, FacilitatorListQuery

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.pacts import FacilitatorListItemDTO, PersonalDataFieldDTO


_FACILITATORS_PAGE_SIZE = 50  # ponytail: revisit after dogfooding


def _format_field_value(*, value: str | list[str] | bool | None) -> str:
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, list):
        return ", ".join(value)
    return value or ""


def _builtin_cell(*, key: str, facilitator: FacilitatorListItemDTO) -> str:
    if key == "name":
        return facilitator.display_name
    if key == "linked":
        return _("Linked") if facilitator.user_id else _("None")
    if key == "sessions":
        return str(facilitator.session_count)
    return str(
        ACCREDITATION_TYPE_LABELS[AccreditationType(facilitator.accreditation_type)]
    )


class FacilitatorsPageView(PanelAccessMixin, EventContextMixin, View):
    """List facilitators for an event."""

    request: PanelRequest

    def _read_query(self) -> FacilitatorListQuery:
        accreditation = self.request.GET.get("accreditation", "").strip()
        return FacilitatorListQuery(
            search=self.request.GET.get("search", "").strip(),
            accreditation=(accreditation if accreditation in AccreditationType else ""),
            flagged=self.request.GET.get("flagged") == "true",
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

        raw_values = self.request.services.facilitator_panel.column_values(
            facilitator_ids=[f.pk for f in page_obj.object_list],
            field_ids=[
                column.field.pk
                for column in list_context.columns
                if column.field is not None
            ],
        )
        # One ready-to-render string per (facilitator, column), so the template
        # renders every column the same way whatever the organizer chose.
        column_values = {
            facilitator.pk: {
                column.key: (
                    _format_field_value(
                        value=raw_values.get(facilitator.pk, {}).get(column.field.slug)
                    )
                    if column.field is not None
                    else _builtin_cell(key=column.key, facilitator=facilitator)
                )
                for column in list_context.columns
            }
            for facilitator in page_obj.object_list
        }

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
        context["filter_sort"] = query.sort
        context["filters_active"] = bool(
            query.search
            or query.accreditation
            or query.flagged
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

        linked_user = None
        if facilitator.user_id is not None:
            try:
                linked_user = self.request.di.uow.active_users.read_by_id(
                    facilitator.user_id
                )
            except NotFoundError:
                linked_user = None

        context["active_nav"] = "facilitators"
        context["facilitator"] = facilitator
        context["linked_user"] = linked_user
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

        context["active_nav"] = "facilitators"
        context["form"] = FacilitatorForm()
        return TemplateResponse(self.request, "panel/facilitator-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = FacilitatorForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "facilitators"
            context["form"] = form
            return TemplateResponse(
                self.request, "panel/facilitator-create.html", context
            )

        display_name = form.cleaned_data["display_name"]
        facilitator_slug = make_unique_slug(
            display_name,
            "facilitator",
            lambda s: self.request.di.uow.facilitators.slug_exists(current_event.pk, s),
        )
        self.request.di.uow.facilitators.create(
            FacilitatorData(
                accreditation_type=form.cleaned_data["accreditation_type"],
                display_name=display_name,
                event_id=current_event.pk,
                slug=facilitator_slug,
                user_id=None,
            )
        )
        messages.success(self.request, _("Facilitator created successfully."))
        return redirect("panel:facilitators", slug=slug)


class FacilitatorEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing facilitator."""

    request: PanelRequest

    def _get_personal_fields(
        self, event_pk: int, facilitator_pk: int
    ) -> list[tuple[PersonalDataFieldDTO, str | list[str] | bool | None]]:
        fields = self.request.di.uow.personal_data_fields.list_by_event(event_pk)
        values = (
            self.request.di.uow.personal_data_field_values.read_for_facilitator_event(
                facilitator_pk, event_pk
            )
        )
        return [(field, values.get(field.slug)) for field in fields]

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

        personal_fields = self._get_personal_fields(current_event.pk, facilitator.pk)
        context["active_nav"] = "facilitators"
        context["facilitator"] = facilitator
        context["form"] = FacilitatorEditForm(
            initial={
                "accreditation_type": facilitator.accreditation_type,
                "internal_comment": facilitator.internal_comment,
            }
        )
        context["personal_fields"] = personal_fields
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
        if not form.is_valid():
            personal_fields = self._get_personal_fields(
                current_event.pk, facilitator.pk
            )
            context["active_nav"] = "facilitators"
            context["facilitator"] = facilitator
            context["form"] = form
            context["personal_fields"] = personal_fields
            return TemplateResponse(
                self.request, "panel/facilitator-edit.html", context
            )

        all_personal_fields = self.request.di.uow.personal_data_fields.list_by_event(
            current_event.pk
        )
        entries: list[PersonalDataFieldValueData] = []
        for field in all_personal_fields:
            key = f"personal_{field.slug}"
            if field.field_type == "checkbox":
                value: str | list[str] | bool = self.request.POST.get(key) == "true"
            elif field.is_multiple:
                value = self.request.POST.getlist(key)
            else:
                value = self.request.POST.get(key, "")
                if field.allow_custom and not value:
                    value = self.request.POST.get(f"{key}_custom", "")
            entries.append(
                PersonalDataFieldValueData(
                    facilitator_id=facilitator.pk,
                    event_id=current_event.pk,
                    field_id=field.pk,
                    value=value,
                )
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

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        raw_ids = self.request.GET.getlist("ids")
        preselected_ids = {int(fid) for fid in raw_ids if fid.isdigit()}

        context["active_nav"] = "facilitators"
        context["active_tab"] = "merge"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["facilitators"] = self.request.di.uow.facilitators.list_by_event(
            current_event.pk
        )
        context["preselected_ids"] = preselected_ids
        context["error"] = None
        return TemplateResponse(self.request, "panel/facilitator-merge.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        all_facilitators = self.request.di.uow.facilitators.list_by_event(
            current_event.pk
        )
        valid_pks = {f.pk for f in all_facilitators}
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
            context["active_nav"] = "facilitators"
            context["active_tab"] = "merge"
            context["tab_urls"] = facilitator_tab_urls(slug)
            context["facilitators"] = all_facilitators
            context["preselected_ids"] = set(selected_ids)
            context["error"] = _(
                "Select at least two facilitators and choose a merge target."
            )
            return TemplateResponse(
                self.request, "panel/facilitator-merge.html", context
            )

        source_ids = [fid for fid in selected_ids if fid != target_id]
        try:
            FacilitatorMergeService(self.request.di.uow).merge(target_id, source_ids)
        except FacilitatorMergeError:
            context["active_nav"] = "facilitators"
            context["active_tab"] = "merge"
            context["tab_urls"] = facilitator_tab_urls(slug)
            context["facilitators"] = all_facilitators
            context["preselected_ids"] = set(selected_ids)
            context["error"] = _(
                "Cannot merge facilitators that each have a linked user account."
            )
            return TemplateResponse(
                self.request, "panel/facilitator-merge.html", context
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
