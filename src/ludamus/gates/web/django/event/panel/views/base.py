from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _

from ludamus.gates.web.django.panel import PanelPermissionResponseMixin
from ludamus.pacts.legacy import NotFoundError

if TYPE_CHECKING:
    from ludamus.pacts import AuthenticatedRequestContext, EventDTO
    from ludamus.pacts.services import ServicesProtocol


def settings_tab_urls(slug: str) -> dict[str, str]:
    return {
        "general": reverse("panel:event-settings", kwargs={"slug": slug}),
        "proposals": reverse("panel:event-proposal-settings", kwargs={"slug": slug}),
        "enrollment": reverse("panel:event-enrollment-settings", kwargs={"slug": slug}),
        "display": reverse("panel:event-display-settings", kwargs={"slug": slug}),
        "integrations": reverse(
            "panel:event-integration-settings", kwargs={"slug": slug}
        ),
    }


class EventPanelRequest(HttpRequest):
    context: AuthenticatedRequestContext
    services: ServicesProtocol


class EventPanelAccessMixin(PanelPermissionResponseMixin, UserPassesTestMixin):
    request: EventPanelRequest

    def test_func(self) -> bool:
        return self.request.services.sphere_panel.is_manager(
            self.request.context.current_sphere_id,
            self.request.context.current_user_slug,
        )


class EventContextMixin:
    request: EventPanelRequest

    def get_event_context(self, slug: str) -> tuple[dict[str, object], EventDTO | None]:
        try:
            page = self.request.services.event_panel.load_context(
                self.request.context.current_sphere_id, slug
            )
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return {}, None

        return {
            "events": page.events,
            "current_event": page.current_event,
            "is_proposal_active": page.is_proposal_active,
            "stats": page.stats.model_dump(),
        }, page.current_event

    def get_current_event(self, slug: str) -> EventDTO | None:
        try:
            return self.request.services.events.read_by_slug(
                self.request.context.current_sphere_id, slug
            )
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return None
