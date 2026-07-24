"""Facilitator views (list, detail, create, edit, merge)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    facilitator_detail_tab_urls,
    facilitator_tab_urls,
    paginate,
)
from ludamus.gates.web.django.forms import (
    ACCREDITATION_TYPE_LABELS,
    FacilitatorEditForm,
    FacilitatorForm,
)
from ludamus.gates.web.django.helpers import parse_dynamic_field_value
from ludamus.pacts import (
    FacilitatorMergeError,
    FacilitatorUpdateData,
    NotFoundError,
    PersonalDataFieldValueData,
)
from ludamus.pacts.panel import (
    FacilitatorCreateData,
    FacilitatorListQuery,
    FacilitatorMergeData,
)
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.pacts import FacilitatorListItemDTO, PersonalDataFieldDTO
    from ludamus.pacts.panel import (
        FacilitatorMergeContextDTO,
        FacilitatorPanelServiceProtocol,
        PanelColumnDTO,
    )


def _personal_entries_from_post(
    *,
    request: PanelRequest,
    fields: Sequence[PersonalDataFieldDTO],
    facilitator_id: int,
    event_id: int,
) -> list[PersonalDataFieldValueData]:
    return [
        PersonalDataFieldValueData(
            facilitator_id=facilitator_id,
            event_id=event_id,
            field_id=field.pk,
            value=parse_dynamic_field_value(
                request=request, field=field, key=f"personal_{field.slug}"
            ),
        )
        for field in fields
    ]


type _FieldValue = str | list[str] | bool


def _format_field_value(*, value: _FieldValue | None) -> str:
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


def _build_column_values(
    *,
    panel: FacilitatorPanelServiceProtocol,
    facilitators: Sequence[FacilitatorListItemDTO],
    columns: Sequence[PanelColumnDTO],
) -> dict[int, dict[str, str]]:
    raw_values = panel.column_values(
        facilitator_ids=[f.pk for f in facilitators],
        field_ids=[column.field.pk for column in columns if column.field is not None],
    )
    # One ready-to-render string per (facilitator, column), so the template
    # renders every column the same way whatever the organizer chose.
    return {
        facilitator.pk: {
            column.key: (
                _format_field_value(
                    value=raw_values.get(facilitator.pk, {}).get(column.field.slug)
                )
                if column.field is not None
                else _builtin_cell(key=column.key, facilitator=facilitator)
            )
            for column in columns
        }
        for facilitator in facilitators
    }


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
        page_obj = paginate(self.request, list_context.facilitators)

        column_values = _build_column_values(
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
            detail = self.request.services.facilitator_panel.detail_context(
                event_id=current_event.pk, facilitator_slug=facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        context["active_nav"] = "facilitators"
        context["active_tab"] = "details"
        context["tab_urls"] = facilitator_detail_tab_urls(slug, facilitator_slug)
        context["facilitator"] = detail.facilitator
        context["linked_user"] = detail.linked_user
        context["accreditation_type_display"] = ACCREDITATION_TYPE_LABELS[
            AccreditationType(detail.facilitator.accreditation_type)
        ]
        context["personal_data_items"] = detail.personal_data_items
        context["has_personal_data"] = any(v for _, v in detail.personal_data_items)
        context["sessions"] = detail.sessions
        return TemplateResponse(self.request, "panel/facilitator-detail.html", context)


class FacilitatorHistoryPageView(PanelAccessMixin, EventContextMixin, View):
    """Per-facilitator change history tab."""

    request: PanelRequest

    def get(
        self, _request: PanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.facilitator_panel
        try:
            name, logs = service.facilitator_history(
                event_id=current_event.pk, facilitator_slug=facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        context["active_nav"] = "facilitators"
        context["active_tab"] = "history"
        context["tab_urls"] = facilitator_detail_tab_urls(slug, facilitator_slug)
        context["facilitator_name"] = name
        context["logs"] = logs
        context["field_names"] = (
            self.request.services.personal_data_field_values.list_field_names(
                current_event.pk
            )
        )
        return TemplateResponse(self.request, "panel/facilitator-history.html", context)


class FacilitatorCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new facilitator for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        fields = self.request.services.facilitator_panel.list_fields(current_event.pk)
        context["active_nav"] = "facilitators"
        context["form"] = FacilitatorForm()
        context["personal_fields"] = [(field, None) for field in fields]
        return TemplateResponse(self.request, "panel/facilitator-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.facilitator_panel
        fields = service.list_fields(current_event.pk)
        form = FacilitatorForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "facilitators"
            context["form"] = form
            context["personal_fields"] = [(field, None) for field in fields]
            return TemplateResponse(
                self.request, "panel/facilitator-create.html", context
            )

        display_name = form.cleaned_data["display_name"]
        service.create_facilitator(
            event_id=current_event.pk,
            data=FacilitatorCreateData(
                display_name=display_name,
                base_slug=slugify(display_name),
                accreditation_type=form.cleaned_data["accreditation_type"],
                values={
                    field.pk: parse_dynamic_field_value(
                        request=self.request, field=field, key=f"personal_{field.slug}"
                    )
                    for field in fields
                },
            ),
            user_id=self.request.context.current_user_id,
        )
        messages.success(self.request, _("Facilitator created successfully."))
        return redirect("panel:facilitators", slug=slug)


class FacilitatorEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing facilitator."""

    request: PanelRequest

    def get(
        self, _request: PanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            detail = self.request.services.facilitator_panel.detail_context(
                event_id=current_event.pk, facilitator_slug=facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        facilitator = detail.facilitator
        context["active_nav"] = "facilitators"
        context["facilitator"] = facilitator
        context["form"] = FacilitatorEditForm(
            initial={
                "accreditation_type": facilitator.accreditation_type,
                "internal_comment": facilitator.internal_comment,
            }
        )
        context["personal_fields"] = detail.personal_data_items
        return TemplateResponse(self.request, "panel/facilitator-edit.html", context)

    def post(
        self, _request: PanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            detail = self.request.services.facilitator_panel.detail_context(
                event_id=current_event.pk, facilitator_slug=facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        facilitator = detail.facilitator
        form = FacilitatorEditForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "facilitators"
            context["facilitator"] = facilitator
            context["form"] = form
            context["personal_fields"] = detail.personal_data_items
            return TemplateResponse(
                self.request, "panel/facilitator-edit.html", context
            )

        all_personal_fields = self.request.services.facilitator_panel.list_fields(
            current_event.pk
        )
        entries = _personal_entries_from_post(
            request=self.request,
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


_MIN_MERGE = 2


def _attributed(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    # Distinct values in facilitator order, each carrying the facilitators
    # that hold it — the reconcile screen says whose value you are keeping.
    groups: dict[str, list[str]] = {}
    for name, value in pairs:
        groups.setdefault(value, []).append(name)
    return [(value, ", ".join(names)) for value, names in groups.items()]


def _field_choices(
    merge_context: FacilitatorMergeContextDTO,
) -> list[tuple[PersonalDataFieldDTO, list[tuple[int, str, str]]]]:
    # One entry per field somebody answered, with the distinct answers in
    choices: list[tuple[PersonalDataFieldDTO, list[tuple[int, str, str]]]] = []
    for field in merge_context.fields:
        groups: list[tuple[int, _FieldValue, list[str]]] = []
        for facilitator in merge_context.facilitators:
            value = merge_context.values.get(facilitator.pk, {}).get(field.slug)
            if not value:
                continue
            for _pk, existing, names in groups:
                if existing == value:
                    names.append(facilitator.display_name)
                    break
            else:
                groups.append((facilitator.pk, value, [facilitator.display_name]))
        if groups:
            choices.append(
                (
                    field,
                    [
                        (pk, _format_field_value(value=value), ", ".join(names))
                        for pk, value, names in groups
                    ],
                )
            )
    return choices


class FacilitatorMergePageView(PanelAccessMixin, EventContextMixin, View):
    """Search-and-collect merge flow with a reconcile-then-confirm screen."""

    request: PanelRequest

    def _basket_slugs(self) -> list[str]:
        slugs = self.request.GET.getlist("facilitator_slugs")
        if add := self.request.GET.get("add", ""):
            slugs = [*slugs, add]
        if remove := self.request.GET.get("remove", ""):
            slugs = [s for s in slugs if s != remove]
        return list(dict.fromkeys(slugs))

    @staticmethod
    def _base_context(context: dict[str, object], slug: str) -> None:
        context["active_nav"] = "facilitators"
        context["active_tab"] = "merge"
        context["tab_urls"] = facilitator_tab_urls(slug)

    def _render_search(
        self,
        *,
        context: dict[str, object],
        slug: str,
        event_id: int,
        basket_slugs: list[str],
    ) -> HttpResponse:
        panel = self.request.services.facilitator_panel
        everyone = panel.list_context(
            event_id=event_id, query=FacilitatorListQuery()
        ).facilitators
        by_slug = {f.slug: f for f in everyone}
        # Stale basket entries (renamed or already merged away) drop silently.
        basket = [by_slug[s] for s in basket_slugs if s in by_slug]
        search = self.request.GET.get("q", "").strip()
        results: list[FacilitatorListItemDTO] = []
        if search:
            in_basket = {f.slug for f in basket}
            results = [
                f
                for f in panel.list_context(
                    event_id=event_id, query=FacilitatorListQuery(search=search)
                ).facilitators
                if f.slug not in in_basket
            ]
        self._base_context(context, slug)
        context["confirm"] = False
        context["basket"] = basket
        context["search_query"] = search
        context["search_results"] = results
        context["can_merge"] = len(basket) >= _MIN_MERGE
        return TemplateResponse(self.request, "panel/facilitator-merge.html", context)

    def _render_confirm(
        self,
        *,
        context: dict[str, object],
        slug: str,
        event_id: int,
        basket_slugs: list[str],
        error: str | None,
    ) -> HttpResponse:
        try:
            merge_context = self.request.services.facilitator_panel.merge_context(
                event_id=event_id, facilitator_slugs=basket_slugs
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitator-merge", slug=slug)

        self._base_context(context, slug)
        context["confirm"] = True
        context["facilitators"] = merge_context.facilitators
        context["name_choices"] = list(
            dict.fromkeys(f.display_name for f in merge_context.facilitators)
        )
        context["accreditation_choices"] = [
            (value, ACCREDITATION_TYPE_LABELS[AccreditationType(value)], sources)
            for value, sources in _attributed(
                (f.display_name, f.accreditation_type)
                for f in merge_context.facilitators
            )
        ]
        context["field_choices"] = _field_choices(merge_context)
        context["error"] = error
        return TemplateResponse(self.request, "panel/facilitator-merge.html", context)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        basket_slugs = self._basket_slugs()
        if self.request.GET.get("confirm") and len(basket_slugs) >= _MIN_MERGE:
            return self._render_confirm(
                context=context,
                slug=slug,
                event_id=current_event.pk,
                basket_slugs=basket_slugs,
                error=None,
            )
        return self._render_search(
            context=context,
            slug=slug,
            event_id=current_event.pk,
            basket_slugs=basket_slugs,
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        basket_slugs = list(
            dict.fromkeys(self.request.POST.getlist("facilitator_slugs"))
        )
        keep_values_from = {
            int(key.removeprefix("personal_")): int(self.request.POST.get(key, ""))
            for key in self.request.POST
            if key.startswith("personal_")
            and key.removeprefix("personal_").isdigit()
            and self.request.POST.get(key, "").isdigit()
        }
        try:
            self.request.services.facilitator_panel.merge(
                event_id=current_event.pk,
                target_slug=self.request.POST.get("target_slug", ""),
                facilitator_slugs=basket_slugs,
                data=FacilitatorMergeData(
                    display_name=self.request.POST.get("display_name", "").strip(),
                    accreditation_type=self.request.POST.get("accreditation_type", ""),
                    keep_values_from=keep_values_from,
                ),
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitator-merge", slug=slug)
        except FacilitatorMergeError:
            return self._render_confirm(
                context=context,
                slug=slug,
                event_id=current_event.pk,
                basket_slugs=basket_slugs,
                error=_(
                    "These facilitators cannot be merged. Check the selection, "
                    "the target, and linked accounts."
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


_BULK_FACILITATOR_ACTIONS = ("flag", "unflag", "mark-guest", "merge")


class FacilitatorBulkActionView(PanelAccessMixin, EventContextMixin, View):
    """Apply one triage action to several facilitators at once (POST only)."""

    http_method_names = ("post",)
    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        back = self._redirect_target(slug)
        action = self.request.POST.get("action", "")
        if action not in _BULK_FACILITATOR_ACTIONS:
            messages.error(self.request, _("Unknown bulk action."))
            return redirect(back)

        if not (slugs := self.request.POST.getlist("facilitator_slugs")):
            messages.warning(self.request, _("No facilitators selected."))
            return redirect(back)

        if action == "merge":
            # Hand the selection to the merge flow's basket (PRG, so the
            # bulk form stays a POST).
            base = reverse("panel:facilitator-merge", kwargs={"slug": slug})
            query = urlencode({"facilitator_slugs": slugs}, doseq=True)
            return redirect(f"{base}?{query}")

        applied = missing = 0
        for facilitator_slug in slugs:
            try:
                self._apply(action, current_event.pk, facilitator_slug)
            except NotFoundError:
                missing += 1
            else:
                applied += 1

        self._report(applied=applied, missing=missing)
        return redirect(back)

    def _apply(self, action: str, event_id: int, facilitator_slug: str) -> None:
        panel = self.request.services.facilitator_panel
        if action == "mark-guest":
            panel.set_accreditation(
                event_id=event_id,
                facilitator_slug=facilitator_slug,
                accreditation_type=AccreditationType.GUEST.value,
                user_id=self.request.context.current_user_id,
            )
        else:
            panel.set_flag(
                event_id=event_id,
                facilitator_slug=facilitator_slug,
                flagged=action == "flag",
            )

    def _redirect_target(self, slug: str) -> str:
        next_url = self.request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={self.request.get_host()}
        ):
            return next_url
        return reverse("panel:facilitators", kwargs={"slug": slug})

    def _report(self, *, applied: int, missing: int) -> None:
        if applied:
            messages.success(
                self.request,
                ngettext(
                    "%(count)d facilitator updated.",
                    "%(count)d facilitators updated.",
                    applied,
                )
                % {"count": applied},
            )
        if missing:
            messages.error(
                self.request,
                ngettext(
                    "%(count)d facilitator could not be found.",
                    "%(count)d facilitators could not be found.",
                    missing,
                )
                % {"count": missing},
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
