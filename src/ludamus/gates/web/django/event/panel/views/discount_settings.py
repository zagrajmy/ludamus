from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.forms import (
    DISCOUNT_METHOD_LABELS,
    DiscountRuleForm,
)
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.panel import settings_tab_urls
from ludamus.pacts.discounts import DiscountRuleData, DiscountRuleDTO
from ludamus.pacts.legacy import RedirectError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO

_SETTINGS_URL = "panel:event-discount-settings"
_FORM_TEMPLATE = "panel/discount-rule-form.html"


def _rule_not_found(slug: str) -> RedirectError:
    return RedirectError(
        reverse(_SETTINGS_URL, kwargs={"slug": slug}),
        error=_("Discount rule not found."),
    )


class DiscountSettingsViewMixin(EventContextMixin):
    request: EventPanelRequest

    def tab_context(self, slug: str) -> tuple[dict[str, object], EventDTO]:
        context, current_event = self.require_event_context(slug)
        context.update(
            active_nav="settings",
            active_tab="discounts",
            tab_urls=settings_tab_urls(slug),
        )
        return context, current_event


class EventDiscountSettingsPageView(
    EventPanelAccessMixin, DiscountSettingsViewMixin, View
):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.tab_context(slug)
        context.update(
            rows=[
                {"rule": rule, "method_label": DISCOUNT_METHOD_LABELS[rule.method]}
                for rule in self.request.services.discounts.list_rules(current_event.pk)
            ]
        )
        return TemplateResponse(self.request, "panel/discount-rules.html", context)


class DiscountRuleCreatePageView(
    EventPanelAccessMixin, DiscountSettingsViewMixin, View
):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, _current_event = self.tab_context(slug)
        context.update(form=DiscountRuleForm(), rule=None)
        return TemplateResponse(self.request, _FORM_TEMPLATE, context)

    def post(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        form = DiscountRuleForm(self.request.POST)
        if not form.is_valid():
            context, _current_event = self.tab_context(slug)
            context.update(form=form, rule=None)
            return TemplateResponse(self.request, _FORM_TEMPLATE, context)

        current_event = self.require_current_event(slug)
        self.request.services.discounts.create_rule(
            current_event.pk, DiscountRuleData.model_validate(form.cleaned_data)
        )
        messages.success(self.request, _("Discount rule created."))
        return redirect(_SETTINGS_URL, slug=slug)


class DiscountRuleEditPageView(EventPanelAccessMixin, DiscountSettingsViewMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.tab_context(slug)
        rule = self._read_rule(slug=slug, event_pk=current_event.pk, pk=pk)
        context.update(form=DiscountRuleForm(initial=rule.model_dump()), rule=rule)
        return TemplateResponse(self.request, _FORM_TEMPLATE, context)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        form = DiscountRuleForm(self.request.POST)
        # Only the re-render needs the tab context; the saving path redirects,
        # so it resolves the event without the sidebar and stats behind it.
        if not form.is_valid():
            context, current_event = self.tab_context(slug)
            rule = self._read_rule(slug=slug, event_pk=current_event.pk, pk=pk)
            context.update(form=form, rule=rule)
            return TemplateResponse(self.request, _FORM_TEMPLATE, context)

        current_event = self.require_current_event(slug)
        updated = self.request.services.discounts.update_rule(
            event_pk=current_event.pk,
            pk=pk,
            data=DiscountRuleData.model_validate(form.cleaned_data),
        )
        if updated is None:
            raise _rule_not_found(slug)
        messages.success(self.request, _("Discount rule saved."))
        return redirect(_SETTINGS_URL, slug=slug)

    def _read_rule(self, *, slug: str, event_pk: int, pk: int) -> DiscountRuleDTO:
        if (rule := self.request.services.discounts.read_rule(event_pk, pk)) is None:
            raise _rule_not_found(slug)
        return rule


class DiscountRuleDeleteActionView(
    EventPanelAccessMixin, DiscountSettingsViewMixin, View
):
    request: EventPanelRequest
    http_method_names = ("post",)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        current_event = self.require_current_event(slug)
        if not self.request.services.discounts.delete_rule(current_event.pk, pk):
            raise _rule_not_found(slug)
        messages.success(self.request, _("Discount rule deleted."))
        return redirect(_SETTINGS_URL, slug=slug)
