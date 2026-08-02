"""Post-schedule confirmation tracking: dashboard and per-block working list."""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.chronology.panel.views.timetable import timetable_tab_urls
from ludamus.pacts.legacy import NotFoundError

_SCOPES = ("session", "email", "facilitator")


class ConfirmationsPageView(PanelAccessMixin, EventContextMixin, View):
    """Confirmation progress for the event, or for one block once chosen."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        sorted_tracks, managed_pks, filter_track_pk = self.get_track_filter_context(
            current_event.pk
        )

        context["active_nav"] = "timetable"
        context["all_tracks"] = sorted_tracks
        context["managed_track_pks"] = managed_pks
        context["filter_track_pk"] = filter_track_pk
        # No block chosen: the event-wide dashboard answers "where do I start".
        # A block chosen: the facilitators of that block, ready to work through.
        context["dashboard"] = (
            None
            if filter_track_pk
            else self.request.services.confirmations.dashboard(current_event.pk)
        )
        context["track_view"] = (
            self.request.services.confirmations.track_view(
                event_pk=current_event.pk, track_pk=filter_track_pk
            )
            if filter_track_pk
            else None
        )
        context["slug"] = slug
        # Where the claim/step-down round trip comes back to.
        context["next_url"] = self.request.get_full_path()
        context["tab_urls"] = timetable_tab_urls(slug)
        context["active_tab"] = "confirmations"
        return TemplateResponse(
            self.request, "panel/timetable-confirmations.html", context
        )


class ConfirmationsConfirmActionView(PanelAccessMixin, EventContextMixin, View):
    """POST: set confirmation over one item, one contact address, or all."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        current_event = self.require_current_event(slug)
        post = self.request.POST
        scope = post.get("scope", "")
        facilitator_raw = post.get("facilitator_pk", "")
        track_raw = post.get("track_pk", "")
        agenda_item_raw = post.get("agenda_item_pk", "")
        if (
            scope not in _SCOPES
            or not facilitator_raw.isdigit()
            or not track_raw.isdigit()
            or (scope == "session" and not agenda_item_raw.isdigit())
        ):
            return HttpResponse(status=422)

        try:
            self.request.services.confirmations.set_confirmed(
                event_pk=current_event.pk,
                facilitator_pk=int(facilitator_raw),
                # An unchecked checkbox sends nothing, which is the "no longer
                # confirmed" case.
                confirmed=post.get("confirmed") == "true",
                # The empty address is a real group, so "no filter" has to be
                # None rather than "".
                contact_email=(
                    post.get("contact_email", "") if scope == "email" else None
                ),
                agenda_item_pk=int(agenda_item_raw) if scope == "session" else None,
            )
            facilitator = self.request.services.confirmations.facilitator_card(
                event_pk=current_event.pk,
                track_pk=int(track_raw),
                facilitator_pk=int(facilitator_raw),
            )
        except NotFoundError:
            return HttpResponse(status=422)

        # The one card that changed comes back rendered, so its progress and
        # its folded state stay true without reloading the page.
        return TemplateResponse(
            self.request,
            "panel/parts/confirmation-facilitator-card.html",
            {
                "facilitator": facilitator,
                "slug": slug,
                "current_event": current_event,
                "filter_track_pk": int(track_raw),
                "next_url": post.get("next", ""),
            },
        )
