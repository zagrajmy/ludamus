"""Facilitator views (list, detail, create, edit, merge)."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import urlencode
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
    format_field_value,
    pagination_context,
    safe_next_url,
)
from ludamus.gates.web.django.chronology.panel.views.columns import (
    FACILITATOR_COLUMNS,
    column_views,
    facilitator_column_values,
)
from ludamus.gates.web.django.dynamic_fields import answered_value
from ludamus.gates.web.django.event.panel.views.facilitator_actions import (
    ORGANIZER_REFUSALS,
    FacilitatorActionView,
)
from ludamus.gates.web.django.event.panel.views.facilitator_fields import (
    PERSONAL_PREFIX,
    personal_descriptors,
    personal_fields_form,
)
from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS, FacilitatorForm
from ludamus.gates.web.django.sphere.marks import attach_facilitator_guild_marks
from ludamus.mills.panel_facilitators import (
    MIN_MERGE_FACILITATORS,
    accreditation_reconcile,
    field_reconcile,
    name_reconcile,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.panel import (
    FacilitatorCreateData,
    FacilitatorListQuery,
    FacilitatorMergeData,
    FacilitatorMergeError,
    MergeErrorReason,
)
from ludamus.pacts.submissions import (
    AccreditationType,
    FacilitatorActionError,
    OrganizerActionRefusal,
)

if TYPE_CHECKING:
    from django.http import HttpResponse


# A tampered `?organizer=` value falls back to "all", so the toolbar never
# shows a selected option the list is not actually filtered by.
_ORGANIZER_FILTERS = ("mine", "unassigned")


def _merge_error_message(reason: MergeErrorReason) -> str:
    # Built per call so gettext resolves in the active request language.
    messages_by_reason = {
        MergeErrorReason.TOO_FEW: _("Select at least two facilitators to merge."),
        MergeErrorReason.NO_TARGET: _(
            "Choose which of the selected facilitators the others merge into."
        ),
        MergeErrorReason.NO_DISPLAY_NAME: _(
            "Choose the display name the merged facilitator keeps."
        ),
        MergeErrorReason.BAD_ACCREDITATION: _(
            "Choose the accreditation the merged facilitator keeps."
        ),
        MergeErrorReason.MULTIPLE_LINKED: _(
            "These facilitators each have a linked user account. Unlink all but "
            "one before merging."
        ),
    }
    return str(messages_by_reason[reason])


class FacilitatorsPageView(PanelAccessMixin, EventContextMixin, View):
    """List facilitators for an event."""

    request: PanelRequest

    def _read_query(self) -> FacilitatorListQuery:
        accreditation = self.request.GET.get("accreditation", "").strip()
        organizer = self.request.GET.get("organizer", "").strip()
        return FacilitatorListQuery(
            search=self.request.GET.get("search", "").strip(),
            accreditation=(accreditation if accreditation in AccreditationType else ""),
            deleted=self.request.GET.get("deleted") == "true",
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
        pagination = pagination_context(self.request, list_context.facilitators)
        page_obj = pagination["page_obj"]

        guilds = self.request.services.guilds
        sphere_id = current_event.sphere_id
        facilitators = list(page_obj.object_list)
        attach_facilitator_guild_marks(facilitators, guilds=guilds, sphere_id=sphere_id)
        cells = facilitator_column_values(
            panel=self.request.services.facilitator_panel,
            facilitators=facilitators,
            columns=list_context.columns,
        )

        context["active_nav"] = "facilitators"
        context["active_tab"] = "list"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["facilitators"] = facilitators
        context.update(pagination)
        context["columns"] = column_views(list_context.columns, FACILITATOR_COLUMNS)
        context["guild_options"] = guilds.list_for_sphere(sphere_id=sphere_id)
        context["column_values"] = cells
        context["filterable_fields"] = list_context.filterable_fields
        context["filter_fields"] = {
            field.pk: query.raw_field_filters.get(field.pk, "")
            for field in list_context.filterable_fields
        }
        context["filter_search"] = query.search
        context["filter_accreditation"] = query.accreditation or None
        context["filter_deleted"] = query.deleted
        context["filter_organizer"] = query.organizer
        context["filter_sort"] = query.sort
        context["filters_active"] = bool(
            query.search
            or query.accreditation
            or query.deleted
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
            detail = self.request.services.facilitator_panel.detail_context(
                event_id=current_event.pk,
                facilitator_slug=facilitator_slug,
                include_deleted=True,
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        context["active_nav"] = "facilitators"
        context["active_tab"] = "details"
        context["tab_urls"] = facilitator_detail_tab_urls(slug, facilitator_slug)
        context["facilitator"] = detail.facilitator
        context["linked_user"] = detail.linked_user
        context["guild"] = self.request.services.guilds.mark_for_facilitator(
            sphere_id=current_event.sphere_id, facilitator_pk=detail.facilitator.pk
        )
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
        context["item_name"] = name
        context["back_url"] = reverse("panel:facilitators", kwargs={"slug": slug})
        context["back_label"] = _("Facilitators")
        context["logs"] = logs
        context["field_names"] = (
            self.request.services.personal_data_field_values.list_field_names(
                current_event.pk
            )
        )
        return TemplateResponse(self.request, "panel/item-history.html", context)


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
        context["field_descriptors"] = personal_descriptors(
            fields, personal_fields_form(fields=fields)
        )
        return TemplateResponse(self.request, "panel/facilitator-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.facilitator_panel
        fields = service.list_fields(current_event.pk)
        form = FacilitatorForm(self.request.POST)
        fields_form = personal_fields_form(fields=fields, data=self.request.POST)
        if not form.is_valid() or not fields_form.is_valid():
            context["active_nav"] = "facilitators"
            context["form"] = form
            context["field_descriptors"] = personal_descriptors(fields, fields_form)
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
                organizer_id=(
                    self.request.context.current_user_id
                    if form.cleaned_data["assign_me"]
                    else None
                ),
                values={
                    field.pk: answered_value(
                        prefix=PERSONAL_PREFIX, field_def=field, form=fields_form
                    )
                    for field in fields
                },
            ),
            user_id=self.request.context.current_user_id,
        )
        messages.success(self.request, _("Facilitator created successfully."))
        return redirect("panel:facilitators", slug=slug)


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
    def _base_context(context: dict[str, Any], slug: str) -> None:
        context["active_nav"] = "facilitators"
        context["active_tab"] = "merge"
        context["tab_urls"] = facilitator_tab_urls(slug)

    def _render_search(
        self,
        *,
        context: dict[str, Any],
        slug: str,
        event_id: int,
        basket_slugs: list[str],
    ) -> HttpResponse:
        panel = self.request.services.facilitator_panel
        basket = panel.merge_basket(event_id=event_id, slugs=basket_slugs)
        in_basket = {f.slug for f in basket}
        search = self.request.GET.get("q", "").strip()
        results = [
            f
            for f in panel.search_candidates(event_id=event_id, search=search)
            if f.slug not in in_basket
        ]
        self._base_context(context, slug)
        context["confirm"] = False
        context["basket"] = basket
        context["search_query"] = search
        context["search_results"] = results
        context["can_merge"] = len(basket) >= MIN_MERGE_FACILITATORS
        return TemplateResponse(self.request, "panel/facilitator-merge.html", context)

    def _render_confirm(
        self,
        *,
        context: dict[str, Any],
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
        name_choices, unanimous_name = name_reconcile(merge_context.facilitators)
        accreditation_values, unanimous_accreditation = accreditation_reconcile(
            merge_context.facilitators
        )
        # Only the disputed fields need a control: the merge keeps a unanimous
        # answer itself, so nothing about it round-trips through the browser.
        field_conflicts, _unanimous_field_values = field_reconcile(merge_context)
        context["confirm"] = True
        context["facilitators"] = merge_context.facilitators
        context["name_choices"] = name_choices
        context["unanimous_display_name"] = unanimous_name
        context["accreditation_choices"] = [
            (
                value,
                ACCREDITATION_TYPE_LABELS[AccreditationType(value)],
                sources,
                checked,
            )
            for value, sources, checked in accreditation_values
        ]
        context["unanimous_accreditation"] = unanimous_accreditation
        context["field_choices"] = [
            (
                field,
                [
                    (pk, format_field_value(value=value), sources, checked)
                    for pk, value, sources, checked in choices
                ],
            )
            for field, choices in field_conflicts
        ]
        context["error"] = error
        return TemplateResponse(self.request, "panel/facilitator-merge.html", context)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        basket_slugs = self._basket_slugs()
        if (
            self.request.GET.get("confirm")
            and len(basket_slugs) >= MIN_MERGE_FACILITATORS
        ):
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
                sphere_id=current_event.sphere_id,
                target_slug=self.request.POST.get("target_slug", ""),
                facilitator_slugs=basket_slugs,
                data=FacilitatorMergeData(
                    display_name=self.request.POST.get("display_name", "").strip(),
                    accreditation_type=self.request.POST.get("accreditation_type", ""),
                    keep_values_from=keep_values_from,
                ),
                user_id=self.request.context.current_user_id,
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitator-merge", slug=slug)
        except FacilitatorMergeError as exc:
            return self._render_confirm(
                context=context,
                slug=slug,
                event_id=current_event.pk,
                basket_slugs=basket_slugs,
                error=_merge_error_message(exc.reason),
            )

        messages.success(self.request, _("Facilitators merged successfully."))
        return redirect("panel:facilitators", slug=slug)


class FacilitatorDeleteActionView(FacilitatorActionView):
    """Delete a facilitator, reversibly (POST only)."""

    success_message = gettext_lazy("Facilitator deleted.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.delete(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            user_id=self.request.context.current_user_id,
        )


class FacilitatorRestoreActionView(FacilitatorActionView):
    """Bring a deleted facilitator back (POST only)."""

    success_message = gettext_lazy("Facilitator restored.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.restore(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            user_id=self.request.context.current_user_id,
        )


class FacilitatorMarkGuestActionView(FacilitatorActionView):
    """Set a facilitator's accreditation to guest (POST only)."""

    success_message = gettext_lazy("Facilitator marked as guest.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.set_accreditation(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            accreditation_type=AccreditationType.GUEST.value,
            user_id=self.request.context.current_user_id,
        )


class FacilitatorAssignOrganizerActionView(FacilitatorActionView):
    """Take an unassigned facilitator on as its organizer (POST only)."""

    success_message = gettext_lazy("You now handle this facilitator.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.assign_organizer(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            organizer_id=self.request.context.current_user_id,
        )


class FacilitatorUnassignOrganizerActionView(FacilitatorActionView):
    """Release a facilitator you organize, so someone else can take it."""

    success_message = gettext_lazy("Stepped down.")

    def _apply(self, event_id: int, facilitator_slug: str) -> None:
        self.request.services.facilitator_panel.unassign_organizer(
            event_id=event_id,
            facilitator_slug=facilitator_slug,
            organizer_id=self.request.context.current_user_id,
            force=self.request.user.is_superuser,
        )


BULK_FACILITATOR_ACTIONS = ("delete", "restore", "mark-guest", "merge")


class FacilitatorBulkActionView(PanelAccessMixin, EventContextMixin, View):
    """Apply one triage action to several facilitators at once (POST only)."""

    http_method_names = ("post",)
    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        back = safe_next_url(
            self.request, reverse("panel:facilitators", kwargs={"slug": slug})
        )
        action = self.request.POST.get("action", "")
        if action not in BULK_FACILITATOR_ACTIONS:
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
        # Counted per reason, so the report states the refusal the service
        # actually gave instead of the one the bulk path assumes.
        refused: Counter[OrganizerActionRefusal] = Counter()
        for facilitator_slug in slugs:
            try:
                self._apply(
                    action=action,
                    event_id=current_event.pk,
                    facilitator_slug=facilitator_slug,
                )
            except NotFoundError:
                missing += 1
            except FacilitatorActionError as exc:
                # One refusal stops that row only; the rest of the selection
                # still goes through.
                refused[exc.refusal] += 1
            else:
                applied += 1

        self._report(applied=applied, missing=missing, refused=refused)
        return redirect(back)

    def _apply(self, *, action: str, event_id: int, facilitator_slug: str) -> None:
        panel = self.request.services.facilitator_panel
        if action == "mark-guest":
            panel.set_accreditation(
                event_id=event_id,
                facilitator_slug=facilitator_slug,
                accreditation_type=AccreditationType.GUEST.value,
                user_id=self.request.context.current_user_id,
            )
        elif action == "delete":
            panel.delete(
                event_id=event_id,
                facilitator_slug=facilitator_slug,
                user_id=self.request.context.current_user_id,
            )
        elif action == "restore":
            panel.restore(
                event_id=event_id,
                facilitator_slug=facilitator_slug,
                user_id=self.request.context.current_user_id,
            )
        else:
            # `post` already checked the membership, so this is unreachable
            # from the web: it exists so an action added to the tuple without
            # a branch here fails in the suite instead of silently restoring
            # the whole selection.
            msg = f"unhandled bulk facilitator action: {action!r}"
            raise ValueError(msg)

    def _report(
        self, *, applied: int, missing: int, refused: Counter[OrganizerActionRefusal]
    ) -> None:
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
        for refusal, count in refused.items():
            # One reason-agnostic wrapper around the refusal the service gave,
            # so the bulk path cannot state a reason it never checked.
            messages.error(
                self.request,
                ngettext(
                    "%(count)d facilitator was skipped: %(reason)s",
                    "%(count)d facilitators were skipped: %(reason)s",
                    count,
                )
                % {"count": count, "reason": ORGANIZER_REFUSALS[refusal]},
            )
