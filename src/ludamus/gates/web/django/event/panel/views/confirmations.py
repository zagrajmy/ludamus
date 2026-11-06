"""Post-schedule confirmation tracking: dashboard and per-block working list."""

from __future__ import annotations

from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelMixin,
    read_track_filter,
)
from ludamus.gates.web.django.panel import PanelRequest, timetable_tab_urls
from ludamus.gates.web.django.request_ids import parse_id
from ludamus.pacts.legacy import NotFoundError

_SCOPES = ("session", "email", "facilitator")


class ConfirmationsPageView(EventPanelMixin, View):
    """Confirmation progress for the event, or for one block once chosen."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        tracks = read_track_filter(self.request, self.current_event.pk)
        filter_track_pk = tracks.selected_pk

        context["active_nav"] = "timetable"
        context["all_tracks"] = tracks.tracks
        context["managed_track_pks"] = tracks.managed_pks
        context["filter_track_pk"] = filter_track_pk
        # No block chosen: the event-wide dashboard answers "where do I start".
        # A block chosen: the facilitators of that block, ready to work through.
        context["dashboard"] = (
            None
            if filter_track_pk
            else self.request.services.confirmations.dashboard(self.current_event.pk)
        )
        context["track_view"] = (
            self.request.services.confirmations.track_view(
                event_pk=self.current_event.pk, track_pk=filter_track_pk
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


class ConfirmationsConfirmActionView(EventPanelMixin, View):
    """POST: set confirmation over one item, one contact address, or all."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        post = self.request.POST
        scope = post.get("scope", "")
        facilitator_pk = parse_id(post.get("facilitator_pk"))
        track_pk = parse_id(post.get("track_pk"))
        session_pk = parse_id(post.get("session_pk")) if scope == "session" else None
        if (
            scope not in _SCOPES
            or facilitator_pk is None
            or track_pk is None
            or (scope == "session" and session_pk is None)
        ):
            return HttpResponse(status=422)

        try:
            self.request.services.confirmations.set_confirmed(
                event_pk=self.current_event.pk,
                facilitator_pk=facilitator_pk,
                # An unchecked checkbox sends nothing, which is the "no longer
                # confirmed" case.
                confirmed=post.get("confirmed") == "true",
                # The empty address is a real group, so "no filter" has to be
                # None rather than "".
                contact_email=(
                    post.get("contact_email", "") if scope == "email" else None
                ),
                session_pk=session_pk,
            )
            facilitator = self.request.services.confirmations.facilitator_card(
                event_pk=self.current_event.pk,
                track_pk=track_pk,
                facilitator_pk=facilitator_pk,
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
                "current_event": self.current_event,
                "filter_track_pk": track_pk,
                "next_url": post.get("next", ""),
            },
        )
