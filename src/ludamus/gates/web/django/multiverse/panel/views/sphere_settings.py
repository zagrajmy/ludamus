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
from ludamus.gates.web.django.sphere.panel_context import sphere_settings_context
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import EncountersPolicy, resolve_uploaded_file_field
from ludamus.pacts.multiverse import SphereSettingsOutcome

if TYPE_CHECKING:
    from django.http import HttpResponse


class SphereSettingsPageView(SphereAccessMixin, View):
    """Display and edit the current sphere's settings."""

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        sphere = self.request.services.sphere_panel.read(
            self.request.context.current_sphere_id
        )
        form = SphereSettingsForm(
            initial={
                "allow_facilitator_session_edit": sphere.allow_facilitator_session_edit,
                "encounters_policy": sphere.encounters_policy.value,
                "logo": stored_file(sphere.logo_url, sphere.logo_original_name),
            }
        )
        return self._render(form, needs_confirmation=False)

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = SphereSettingsForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            # Re-rendered bound, not redirected: the form carries a logo
            # picker, and a toast would throw all of it away.
            return self._render(form, needs_confirmation=False)

        outcome = self.request.services.sphere_panel.update_settings(
            self.request.context.current_sphere_id,
            allow_facilitator_session_edit=form.cleaned_data[
                "allow_facilitator_session_edit"
            ],
            encounters_policy=EncountersPolicy(form.cleaned_data["encounters_policy"]),
            logo=resolve_uploaded_file_field(form.cleaned_data.get("logo")),
            confirmed_encounters_disable=form.cleaned_data[
                "confirmed_encounters_disable"
            ],
        )
        if outcome is SphereSettingsOutcome.NEEDS_CONFIRMATION:
            # Nothing was written, and neither a file input nor the clear
            # box survives the re-render, so a logo change made in the same
            # save is gone from the form. Say so rather than letting the
            # confirming save quietly keep the old one.
            return self._render(
                form,
                needs_confirmation=True,
                lost_logo_change=(
                    "logo" in self.request.FILES or "logo-clear" in self.request.POST
                ),
            )

        messages.success(self.request, _("Sphere settings saved successfully."))
        return redirect("multiverse:panel:sphere-settings")

    def _render(
        self,
        form: SphereSettingsForm,
        *,
        needs_confirmation: bool,
        lost_logo_change: bool = False,
    ) -> HttpResponse:
        base = sphere_settings_context(self.request, active_tab="general")
        return TemplateResponse(
            self.request,
            "multiverse/panel/sphere-settings.html",
            base
            | {
                "form": form,
                "needs_disable_confirmation": needs_confirmation,
                "lost_logo_change": lost_logo_change,
            },
        )
