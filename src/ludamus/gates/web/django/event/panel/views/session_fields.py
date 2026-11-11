"""Session field views for the CFP, plus the icon-preview HTMX partial."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View
from heroicons import IconDoesNotExist

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.gates.web.django.event.panel.views.fields import (
    parse_session_field_form_data,
    undeletable_field_reasons,
)
from ludamus.gates.web.django.forms import SessionFieldForm
from ludamus.gates.web.django.panel import (
    PanelAccessMixin,
    PanelRequest,
    cfp_tab_urls,
    parse_requirement_selection,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.fields import DEFAULT_FIELD_MAX_LENGTH


class SessionFieldsPageView(EventPanelMixin, View):
    """List session fields for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Display session fields list.

        Returns:
            TemplateResponse with the fields list or redirect if not found.
        """
        context = self.panel_context()

        context["active_nav"] = "cfp"
        context["active_tab"] = "session"
        context["tab_urls"] = cfp_tab_urls(slug)
        summaries = self.request.services.session_fields.list_summaries(
            self.current_event.pk
        )
        context["fields"] = summaries
        context["undeletable_field_reasons"] = undeletable_field_reasons(summaries)
        return TemplateResponse(self.request, "panel/session-fields.html", context)


class SessionFieldCreatePageView(EventPanelMixin, View):
    """Create a new session field for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        """Display the session field creation form.

        Returns:
            TemplateResponse with the form or redirect if event not found.
        """
        context = self.panel_context()

        context["active_nav"] = "cfp"
        context["form"] = SessionFieldForm(
            initial={"max_length": DEFAULT_FIELD_MAX_LENGTH}
        )
        context["categories"] = self.request.services.session_fields.list_categories(
            self.current_event.pk
        )
        context["required_category_pks"] = set()
        context["optional_category_pks"] = set()
        return TemplateResponse(
            self.request, "panel/session-field-create.html", context
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Handle session field creation.

        Returns:
            Redirect response to fields list on success, or form with errors.
        """
        context = self.panel_context()

        form = SessionFieldForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "cfp"
            context["form"] = form
            context["categories"] = (
                self.request.services.session_fields.list_categories(
                    self.current_event.pk
                )
            )
            cat_reqs = parse_requirement_selection(
                self.request.POST, prefix="category_", order_key="category_order"
            ).requirements
            context["required_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if is_req
            }
            context["optional_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if not is_req
            }
            return TemplateResponse(
                self.request, "panel/session-field-create.html", context
            )

        self.request.services.session_fields.create(
            event_pk=self.current_event.pk,
            data=parse_session_field_form_data(form),
            category_requirements=parse_requirement_selection(
                self.request.POST, prefix="category_", order_key="category_order"
            ),
        )

        messages.success(self.request, _("Session field created successfully."))
        return redirect("panel:session-fields", slug=slug)


class SessionFieldEditPageView(EventPanelMixin, View):
    """Edit an existing session field."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, field_slug: str) -> HttpResponse:
        """Display the session field edit form.

        Returns:
            TemplateResponse with the form or redirect if not found.
        """
        context = self.panel_context()

        try:
            field, field_cats = self.request.services.session_fields.read(
                self.current_event.pk, field_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Session field not found."))
            return redirect("panel:session-fields", slug=slug)

        context["active_nav"] = "cfp"
        context["field"] = field
        initial = {
            "name": field.name,
            "question": field.question,
            "max_length": field.max_length,
            "help_text": field.help_text,
            "icon": field.icon,
            "is_public": field.is_public,
        }
        if field.field_type == "select":
            initial["options"] = "\n".join(o.label for o in field.options)
            initial["is_multiple"] = field.is_multiple
            initial["allow_custom"] = field.allow_custom
        context["form"] = SessionFieldForm(initial=initial)
        context["categories"] = self.request.services.session_fields.list_categories(
            self.current_event.pk
        )
        context["required_category_pks"] = {
            pk for pk, is_req in field_cats.items() if is_req
        }
        context["optional_category_pks"] = {
            pk for pk, is_req in field_cats.items() if not is_req
        }
        return TemplateResponse(self.request, "panel/session-field-edit.html", context)

    def post(self, _request: PanelRequest, slug: str, field_slug: str) -> HttpResponse:
        """Handle session field update.

        Returns:
            Redirect response to fields list on success, or form with errors.
        """
        context = self.panel_context()

        try:
            field = self.request.services.session_fields.read(
                self.current_event.pk, field_slug
            )[0]
        except NotFoundError:
            messages.error(self.request, _("Session field not found."))
            return redirect("panel:session-fields", slug=slug)

        # The edit page renders no type control; the options check needs one.
        data = self.request.POST.copy()
        data["field_type"] = field.field_type
        form = SessionFieldForm(data)
        if not form.is_valid():
            context["active_nav"] = "cfp"
            context["field"] = field
            context["form"] = form
            context["categories"] = (
                self.request.services.session_fields.list_categories(
                    self.current_event.pk
                )
            )
            cat_reqs = parse_requirement_selection(
                self.request.POST, prefix="category_", order_key="category_order"
            ).requirements
            context["required_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if is_req
            }
            context["optional_category_pks"] = {
                pk for pk, is_req in cat_reqs.items() if not is_req
            }
            return TemplateResponse(
                self.request, "panel/session-field-edit.html", context
            )

        name = form.cleaned_data["name"]
        question = form.cleaned_data["question"]
        max_length = form.cleaned_data.get("max_length") or 0
        help_text = form.cleaned_data.get("help_text") or ""
        options_text = form.cleaned_data.get("options") or ""
        options: list[str] | None = None
        if field.field_type == "select":
            options = [o.strip() for o in options_text.split("\n") if o.strip()] or []
        self.request.services.session_fields.update(
            event_pk=self.current_event.pk,
            field_slug=field_slug,
            data={
                "name": name,
                "question": question,
                "max_length": max_length,
                "help_text": help_text,
                "icon": form.cleaned_data.get("icon") or "",
                "is_public": form.cleaned_data.get("is_public", False),
                "options": options,
                "is_multiple": form.cleaned_data.get("is_multiple") or False,
                "allow_custom": form.cleaned_data.get("allow_custom") or False,
            },
            category_requirements=parse_requirement_selection(
                self.request.POST, prefix="category_", order_key="category_order"
            ),
        )

        messages.success(self.request, _("Session field updated successfully."))
        return redirect("panel:session-fields", slug=slug)


class SessionFieldDeleteActionView(EventPanelMixin, View):
    """Delete a session field (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, field_slug: str) -> HttpResponse:
        """Handle session field deletion.

        Returns:
            Redirect response to session fields list.
        """
        try:
            deleted = self.request.services.session_fields.delete(
                self.current_event.pk, field_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Session field not found."))
            return redirect("panel:session-fields", slug=slug)
        if not deleted:
            messages.error(
                self.request, _("Cannot delete field that is used in categories.")
            )
            return redirect("panel:session-fields", slug=slug)

        messages.success(self.request, _("Session field deleted successfully."))
        return redirect("panel:session-fields", slug=slug)


class IconPreviewPartView(PanelAccessMixin, View):
    """HTMX partial: renders an icon preview or empty response."""

    request: PanelRequest

    def get(self, _request: PanelRequest) -> HttpResponse:
        if not (icon_name := self.request.GET.get("icon", "").strip()):
            return HttpResponse("")
        try:
            html = render_to_string(
                "panel/parts/icon_preview.html",
                {"icon_name": icon_name},
                request=self.request,
            )
        except IconDoesNotExist:
            return HttpResponse("")
        return HttpResponse(html)
