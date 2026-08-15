from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import safe_next_url
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.sphere.forms import FacilitatorAssignGuildForm
from ludamus.pacts import NotFoundError
from ludamus.pacts.submissions import FacilitatorActionError, OrganizerActionRefusal

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import _StrPromise


# Why the claim or the step-down did not apply. A double-click and a genuine
# clash are different stories, so they get different messages.
_ORGANIZER_REFUSALS: dict[OrganizerActionRefusal, _StrPromise] = {
    OrganizerActionRefusal.ALREADY_TAKEN: gettext_lazy(
        "Someone else already handles this facilitator."
    ),
    OrganizerActionRefusal.ALREADY_YOURS: gettext_lazy(
        "You already handle this facilitator."
    ),
    OrganizerActionRefusal.ALREADY_FREE: gettext_lazy(
        "Nobody handles this facilitator."
    ),
    OrganizerActionRefusal.NOT_ORGANIZER: gettext_lazy(
        "Only the person handling this facilitator can step down."
    ),
}


class FacilitatorActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    http_method_names = ("post",)
    success_message: str | _StrPromise = ""

    def _apply(self, event_id: int, facilitator_slug: str) -> str | _StrPromise | None:
        raise NotImplementedError

    def post(
        self, _request: EventPanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        back = safe_next_url(
            self.request, reverse("panel:facilitators", kwargs={"slug": slug})
        )
        try:
            error = self._apply(current_event.pk, facilitator_slug)
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)
        except FacilitatorActionError as exc:
            messages.error(self.request, _ORGANIZER_REFUSALS[exc.refusal])
            return redirect(back)
        if error:
            messages.error(self.request, error)
            return redirect(back)

        messages.success(self.request, self.success_message)
        return redirect(back)


class FacilitatorAssignGuildActionView(FacilitatorActionView):
    success_message = gettext_lazy("Attached to this guild.")

    def _apply(self, event_id: int, facilitator_slug: str) -> str | _StrPromise | None:
        form = FacilitatorAssignGuildForm(self.request.POST)
        if not form.is_valid():
            return _("Pick a guild.")
        if not self.request.services.facilitator_panel.assign_guild(
            event_id=event_id,
            sphere_id=self.request.context.current_sphere_id,
            facilitator_slug=facilitator_slug,
            guild_pk=form.cleaned_data["guild_pk"],
        ):
            return _("Guild not found.")
        return None
