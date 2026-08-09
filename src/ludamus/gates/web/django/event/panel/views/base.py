from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _

from ludamus.gates.web.django.access import passes_panel_access
from ludamus.gates.web.django.panel import PanelPermissionResponseMixin
from ludamus.pacts.legacy import NotFoundError, RedirectError
from ludamus.pacts.multiverse import Capability

if TYPE_CHECKING:
    from ludamus.pacts import AuthenticatedRequestContext, EventDTO
    from ludamus.pacts.services import ServicesProtocol


class EventPanelRequest(HttpRequest):
    context: AuthenticatedRequestContext
    services: ServicesProtocol


class EventPanelAccessMixin(PanelPermissionResponseMixin, UserPassesTestMixin):
    request: EventPanelRequest

    # What this page's buttons stand for. A view whose writes a narrower role
    # may perform names that capability instead; it never names the role.
    write_capability: ClassVar[Capability] = Capability.PANEL_WRITE

    def test_func(self) -> bool:
        return passes_panel_access(self.request, write_capability=self.write_capability)


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

    def require_event_context(self, slug: str) -> tuple[dict[str, object], EventDTO]:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            raise RedirectError(reverse("panel:index"))
        return context, current_event

    def require_current_event(self, slug: str) -> EventDTO:
        if (current_event := self.get_current_event(slug)) is None:
            raise RedirectError(reverse("panel:index"))
        return current_event

    def get_current_event(self, slug: str) -> EventDTO | None:
        try:
            return self.request.services.events.read_by_slug(
                self.request.context.current_sphere_id, slug
            )
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return None
