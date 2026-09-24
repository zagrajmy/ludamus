"""Personal data field views for the CFP."""

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
    cfp_tab_urls,
)
from ludamus.gates.web.django.chronology.panel.views.fields import parse_field_form_data
from ludamus.gates.web.django.forms import PersonalDataFieldForm
from ludamus.pacts import DEFAULT_FIELD_MAX_LENGTH, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.http import HttpResponse

    from ludamus.pacts.submissions import PersonalFieldSummary


def answered_field_reasons(summaries: Iterable[PersonalFieldSummary]) -> dict[int, str]:
    # The same question `delete` refuses on, rendered beside the row instead
    # of taking the click.
    return dict.fromkeys(
        (summary.field.pk for summary in summaries if summary.answer_count),
        _("Already answered"),
    )


class PersonalDataFieldsPageView(PanelAccessMixin, EventContextMixin, View):
    """List personal data fields for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Display personal data fields list.

        Returns:
            TemplateResponse with the fields list or redirect if not found.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.personal_data_fields
        context["active_nav"] = "cfp"
        context["active_tab"] = "host"
        context["tab_urls"] = cfp_tab_urls(slug)
        summaries = service.list_summaries(current_event.pk)
        context["fields"] = summaries
        context["undeletable_field_reasons"] = answered_field_reasons(summaries)
        return TemplateResponse(
            self.request, "panel/personal-data-fields.html", context
        )


class PersonalDataFieldCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new personal data field for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Display the personal data field creation form.

        Returns:
            TemplateResponse with the form or redirect if event not found.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "cfp"
        context["form"] = PersonalDataFieldForm(
            initial={"max_length": DEFAULT_FIELD_MAX_LENGTH, "order": 0}
        )
        return TemplateResponse(
            self.request, "panel/personal-data-field-create.html", context
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Handle personal data field creation.

        Returns:
            Redirect response to fields list on success, or form with errors.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = PersonalDataFieldForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "cfp"
            context["form"] = form
            return TemplateResponse(
                self.request, "panel/personal-data-field-create.html", context
            )

        self.request.services.personal_data_fields.create(
            current_event.pk,
            {
                **parse_field_form_data(form),
                "is_required": form.cleaned_data.get("is_required") or False,
                "order": form.cleaned_data.get("order") or 0,
            },
        )

        messages.success(self.request, _("Personal data field created successfully."))
        return redirect("panel:personal-data-fields", slug=slug)


class PersonalDataFieldEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing personal data field."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, field_slug: str) -> HttpResponse:
        """Display the personal data field edit form.

        Returns:
            TemplateResponse with the form or redirect if not found.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.personal_data_fields
        try:
            field = service.read(current_event.pk, field_slug)
        except NotFoundError:
            messages.error(self.request, _("Personal data field not found."))
            return redirect("panel:personal-data-fields", slug=slug)

        initial = {
            "name": field.name,
            "question": field.question,
            "max_length": field.max_length,
            "help_text": field.help_text,
            "is_public": field.is_public,
            "is_required": field.is_required,
            "order": field.order,
        }
        if field.field_type == "select":
            initial["options"] = "\n".join(o.label for o in field.options)
            initial["is_multiple"] = field.is_multiple
            initial["allow_custom"] = field.allow_custom

        context["active_nav"] = "cfp"
        context["field"] = field
        context["form"] = PersonalDataFieldForm(initial=initial)
        return TemplateResponse(
            self.request, "panel/personal-data-field-edit.html", context
        )

    def post(self, _request: PanelRequest, slug: str, field_slug: str) -> HttpResponse:
        """Handle personal data field update.

        Returns:
            Redirect response to fields list on success, or form with errors.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.personal_data_fields
        try:
            field = service.read(current_event.pk, field_slug)
        except NotFoundError:
            messages.error(self.request, _("Personal data field not found."))
            return redirect("panel:personal-data-fields", slug=slug)

        # The type is fixed after creation, so the form learns it from the
        # field rather than the POST for the checkbox guard.
        data = self.request.POST.copy()
        data["field_type"] = field.field_type
        form = PersonalDataFieldForm(data)
        if not form.is_valid():
            context["active_nav"] = "cfp"
            context["field"] = field
            context["form"] = form
            return TemplateResponse(
                self.request, "panel/personal-data-field-edit.html", context
            )

        service.update(
            event_pk=current_event.pk,
            field_slug=field_slug,
            data={
                **parse_field_form_data(form),
                "is_required": form.cleaned_data.get("is_required") or False,
                "order": form.cleaned_data.get("order") or 0,
            },
        )

        messages.success(self.request, _("Personal data field updated successfully."))
        return redirect("panel:personal-data-fields", slug=slug)


class PersonalDataFieldDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    """Delete a personal data field (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, field_slug: str) -> HttpResponse:
        """Handle personal data field deletion.

        Returns:
            Redirect response to personal data fields list.
        """
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.personal_data_fields
        try:
            deleted = service.delete(current_event.pk, field_slug)
        except NotFoundError:
            messages.error(self.request, _("Personal data field not found."))
            return redirect("panel:personal-data-fields", slug=slug)

        if not deleted:
            messages.error(
                self.request,
                _("Cannot delete a field that people have already answered."),
            )
            return redirect("panel:personal-data-fields", slug=slug)

        messages.success(self.request, _("Personal data field deleted successfully."))
        return redirect("panel:personal-data-fields", slug=slug)
