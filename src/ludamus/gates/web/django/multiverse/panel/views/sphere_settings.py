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
from ludamus.gates.web.django.sphere.pages import SPHERE_PAGE_LABELS
from ludamus.gates.web.django.sphere.panel_context import sphere_settings_context
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import (
    EncounterPublicPolicy,
    SpherePage,
    resolve_uploaded_file_field,
)

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
                "enabled_pages": [page.value for page in sphere.enabled_pages],
                "default_page": sphere.default_page.value,
                "encounter_public_policy": sphere.encounter_public_policy.value,
                "logo": stored_file(sphere.logo_url, sphere.logo_original_name),
            }
        )
        return self._render(form, to_disable=set())

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = SphereSettingsForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            # Re-rendered bound, not redirected: the form carries six fields
            # including a logo picker, and a toast would throw all of it away.
            return self._render(form, to_disable=set())

        sphere_id = self.request.context.current_sphere_id
        service = self.request.services.sphere_panel
        enabled_pages = [
            SpherePage(page) for page in form.cleaned_data["enabled_pages"]
        ]
        to_disable = (
            set(service.read(sphere_id).enabled_pages) - set(enabled_pages)
        ) & service.pages_with_content(sphere_id)
        # Compared page by page: a confirmation given for one page must not
        # authorise disabling another the manager picked afterwards.
        if unconfirmed := to_disable - form.confirmed_pages():
            return self._render(form, to_disable=unconfirmed)

        service.update_settings(
            sphere_id,
            allow_facilitator_session_edit=form.cleaned_data[
                "allow_facilitator_session_edit"
            ],
            enabled_pages=enabled_pages,
            default_page=SpherePage(form.cleaned_data["default_page"]),
            encounter_public_policy=EncounterPublicPolicy(
                form.cleaned_data["encounter_public_policy"]
            ),
            logo=resolve_uploaded_file_field(form.cleaned_data.get("logo")),
        )
        messages.success(self.request, _("Sphere settings saved successfully."))
        return redirect("multiverse:panel:sphere-settings")

    def _render(
        self, form: SphereSettingsForm, *, to_disable: set[SpherePage]
    ) -> HttpResponse:
        base = sphere_settings_context(self.request, active_tab="general")
        return TemplateResponse(
            self.request,
            "multiverse/panel/sphere-settings.html",
            base
            | {
                "form": form,
                "disable_warning_pages": sorted(
                    str(SPHERE_PAGE_LABELS[page]) for page in to_disable
                ),
                "needs_disable_confirmation": bool(to_disable),
                "confirmed_page_disable": ",".join(
                    sorted(page.value for page in to_disable)
                ),
            },
        )
