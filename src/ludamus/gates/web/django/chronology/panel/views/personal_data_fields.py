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
from ludamus.gates.web.django.chronology.panel.views.fields import (
    parse_field_form_data,
    parse_field_requirements,
)
from ludamus.gates.web.django.forms import PersonalDataFieldForm
from ludamus.pacts import DEFAULT_FIELD_MAX_LENGTH, NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse


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
        context["fields"] = service.list_summaries(current_event.pk)
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

        service = self.request.services.personal_data_fields
        form_ctx = service.get_create_form_context(current_event.pk)
        context["active_nav"] = "cfp"
        context["form"] = PersonalDataFieldForm(
            initial={"max_length": DEFAULT_FIELD_MAX_LENGTH}
        )
        context["categories"] = form_ctx.categories
        context["required_category_pks"] = set()
        context["optional_category_pks"] = set()
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

        service = self.request.services.personal_data_fields
        form = PersonalDataFieldForm(self.request.POST)
        cat_reqs, _order = parse_field_requirements(
            self.request.POST, "category_", "category_order"
        )

        if not form.is_valid():
            form_ctx = service.get_create_form_context(current_event.pk)
            context["active_nav"] = "cfp"
            context["form"] = form
            context["categories"] = form_ctx.categories
            context["required_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if is_req
            }
            context["optional_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if not is_req
            }
            return TemplateResponse(
                self.request, "panel/personal-data-field-create.html", context
            )

        service.create(
            event_pk=current_event.pk,
            data=parse_field_form_data(form),
            category_requirements=cat_reqs,
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
            edit_ctx = service.get_edit_form_context(current_event.pk, field_slug)
        except NotFoundError:
            messages.error(self.request, _("Personal data field not found."))
            return redirect("panel:personal-data-fields", slug=slug)

        field = edit_ctx.field
        initial = {
            "name": field.name,
            "question": field.question,
            "max_length": field.max_length,
            "help_text": field.help_text,
            "is_public": field.is_public,
        }
        if field.field_type == "select":
            initial["options"] = "\n".join(o.label for o in field.options)

        context["active_nav"] = "cfp"
        context["field"] = field
        context["form"] = PersonalDataFieldForm(initial=initial)
        context["categories"] = edit_ctx.categories
        context["required_category_pks"] = edit_ctx.required_category_pks
        context["optional_category_pks"] = edit_ctx.optional_category_pks
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
            edit_ctx = service.get_edit_form_context(current_event.pk, field_slug)
        except NotFoundError:
            messages.error(self.request, _("Personal data field not found."))
            return redirect("panel:personal-data-fields", slug=slug)

        field = edit_ctx.field
        form = PersonalDataFieldForm(self.request.POST)
        cat_reqs, _order = parse_field_requirements(
            self.request.POST, "category_", "category_order"
        )

        if not form.is_valid():
            context["active_nav"] = "cfp"
            context["field"] = field
            context["form"] = form
            context["categories"] = edit_ctx.categories
            context["required_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if is_req
            }
            context["optional_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if not is_req
            }
            return TemplateResponse(
                self.request, "panel/personal-data-field-edit.html", context
            )

        options_text = form.cleaned_data.get("options") or ""
        options: list[str] | None = None
        if field.field_type == "select":
            options = [o.strip() for o in options_text.split("\n") if o.strip()] or []

        service.update(
            event_pk=current_event.pk,
            field_slug=field_slug,
            data={
                "name": form.cleaned_data["name"],
                "question": form.cleaned_data["question"],
                "max_length": form.cleaned_data.get("max_length") or 0,
                "help_text": form.cleaned_data.get("help_text") or "",
                "is_public": form.cleaned_data.get("is_public", False),
                "options": options,
            },
            category_requirements=cat_reqs,
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
                self.request, _("Cannot delete field that is used in session types.")
            )
            return redirect("panel:personal-data-fields", slug=slug)

        messages.success(self.request, _("Personal data field deleted successfully."))
        return redirect("panel:personal-data-fields", slug=slug)
