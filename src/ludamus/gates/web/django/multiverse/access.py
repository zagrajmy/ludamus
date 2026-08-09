"""Sphere-scoped access mixin for the multiverse subdomain.

Mirrors `chronology.panel.PanelAccessMixin` minus the event-context
coupling — the multiverse panel is sphere-scoped, not event-scoped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from ludamus.gates.web.django.access import passes_panel_access
from ludamus.pacts.multiverse import Capability

if TYPE_CHECKING:
    from ludamus.pacts import AuthenticatedRequestContext
    from ludamus.pacts.services import ServicesProtocol


class MultiverseRequest(HttpRequest):
    """Request type for multiverse views with services and context."""

    context: AuthenticatedRequestContext
    services: ServicesProtocol


class SphereAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Require the current user to manage the current sphere."""

    request: MultiverseRequest

    write_capability: ClassVar[Capability] = Capability.PANEL_WRITE

    def test_func(self) -> bool:
        return passes_panel_access(self.request, write_capability=self.write_capability)

    def handle_no_permission(self) -> HttpResponseRedirect:
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(
            self.request, _("You don't have permission to access the sphere panel.")
        )
        return redirect("web:index")
