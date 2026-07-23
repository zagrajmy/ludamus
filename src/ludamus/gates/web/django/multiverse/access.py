"""Sphere-scoped access mixin for the multiverse subdomain.

Mirrors `chronology.panel.PanelAccessMixin` minus the event-context
coupling — the multiverse panel is sphere-scoped, not event-scoped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.translation import gettext as _

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

    def test_func(self) -> bool:
        if self.request.user.is_superuser:
            return True
        ctx = self.request.context
        return self.request.services.sphere_panel.is_manager(
            ctx.current_sphere_id, ctx.current_user_slug
        )

    def handle_no_permission(self) -> HttpResponseRedirect:
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(
            self.request, _("You don't have permission to access the sphere panel.")
        )
        return redirect("web:index")
