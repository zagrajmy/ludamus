from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event_deletion import EventDeletionOutcome, NotSphereManagerError
from ludamus.pacts.ids import EventId

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest


def _back_to_ballot(slug: str) -> HttpResponse:
    response = redirect("panel:event-settings", slug=slug)
    response["Location"] += "#event-deletion"
    return response


class EventSettingsApproveDeletionActionView(EventPanelMixin, View):
    request: PanelRequest

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = request.context.current_sphere_id
        event_id = EventId(self.current_event.pk)
        user_id = request.context.current_user_id
        try:
            outcome = request.services.event_deletion.approve(
                sphere_id=sphere_id, event_id=event_id, user_id=user_id
            )
        except NotSphereManagerError:
            messages.error(request, _("Only sphere managers can delete an event."))
            return _back_to_ballot(slug)
        except NotFoundError:
            messages.error(request, _("Event not found."))
            return redirect("panel:index")

        if outcome is EventDeletionOutcome.DELETED:
            messages.success(
                request, _("%(event)s is deleted.") % {"event": self.current_event.name}
            )
            return redirect("panel:index")

        ballot = request.services.event_deletion.read_ballot(
            sphere_id=sphere_id, event_id=event_id, viewer_id=user_id
        )
        messages.success(
            request,
            ngettext(
                "Your approval is in. The event is deleted once %(count)d more "
                "manager approves.",
                "Your approval is in. The event is deleted once %(count)d more "
                "managers approve.",
                ballot.approvals_missing,
            )
            % {"count": ballot.approvals_missing},
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
