from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.gates.web.django.event.panel.views.event_settings import (
    EventSettingsPageView,
)
from ludamus.gates.web.django.settings_forms import EventDeletionConfirmForm
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event_deletion import NotSphereManagerError
from ludamus.pacts.ids import EventId

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest


def _back_to_ballot(slug: str) -> HttpResponse:
    settings_url = reverse("panel:event-settings", kwargs={"slug": slug})
    return redirect(f"{settings_url}#event-deletion")


class EventSettingsApproveDeletionActionView(EventSettingsPageView):
    # A name that does not match comes back as the settings page with the
    # error at the field, so the action renders that page instead of its own.
    http_method_names = ("post",)

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
        form = EventDeletionConfirmForm(
            request.POST, event_name=self.current_event.name
        )
        if not form.is_valid():
            return self.render_page(deletion_form=form)
        try:
            missing = request.services.event_deletion.approve(
                sphere_id=request.context.current_sphere_id,
                event_id=EventId(self.current_event.pk),
                user_id=request.context.current_user_id,
            )
        except NotSphereManagerError:
            messages.error(request, _("Only sphere managers can delete an event."))
            return _back_to_ballot(slug)
        except NotFoundError:
            messages.error(request, _("Event not found."))
            return redirect("panel:index")

        if not missing:
            messages.success(
                request, _("%(event)s is deleted.") % {"event": self.current_event.name}
            )
            return redirect("panel:index")
        messages.success(
            request,
            ngettext(
                "Your approval is in. The event is deleted once %(count)d more "
                "manager approves.",
                "Your approval is in. The event is deleted once %(count)d more "
                "managers approve.",
                missing,
            )
            % {"count": missing},
        )
        return _back_to_ballot(slug)


class EventSettingsWithdrawDeletionActionView(EventPanelMixin, View):
    request: PanelRequest

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
        try:
            request.services.event_deletion.withdraw(
                sphere_id=request.context.current_sphere_id,
                event_id=EventId(self.current_event.pk),
                user_id=request.context.current_user_id,
            )
        except NotSphereManagerError:
            messages.error(request, _("Only sphere managers can delete an event."))
            return _back_to_ballot(slug)
        except NotFoundError:
            messages.error(request, _("Event not found."))
            return redirect("panel:index")
        messages.success(request, _("Your approval is withdrawn."))
        return _back_to_ballot(slug)
