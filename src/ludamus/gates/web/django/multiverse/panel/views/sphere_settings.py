"""Sphere settings — general tab (sphere-wide defaults)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.forms import SphereSettingsForm
from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.multiverse.panel.views.base import sphere_panel_context

if TYPE_CHECKING:
    from django.http import HttpResponse


class SphereSettingsPageView(SphereAccessMixin, View):
    """Display and edit the current sphere's settings."""

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        context = sphere_panel_context(self.request, active_tab="general")
        sphere = self.request.services.sphere_panel.read(
            self.request.context.current_sphere_id
        )
        context["form"] = SphereSettingsForm(
            initial={
                "allow_facilitator_session_edit": sphere.allow_facilitator_session_edit
            }
        )
        return TemplateResponse(
            self.request, "multiverse/panel/sphere-settings.html", context
        )

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = SphereSettingsForm(self.request.POST)
        if not form.is_valid():
            for field_errors in form.errors.values():
                messages.error(self.request, str(field_errors[0]))
            return redirect("multiverse:panel:sphere-settings")

        self.request.services.sphere_panel.update_settings(
            self.request.context.current_sphere_id,
            allow_facilitator_session_edit=form.cleaned_data[
                "allow_facilitator_session_edit"
            ],
        )
        messages.success(self.request, _("Sphere settings saved successfully."))
        return redirect("multiverse:panel:sphere-settings")
