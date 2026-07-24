"""Shared mixins, request type, and helpers for panel views."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _

from ludamus.mills import PanelService, is_proposal_active
from ludamus.pacts import DependencyInjectorProtocol, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts import AuthenticatedRequestContext, EventDTO
    from ludamus.pacts.services import ServicesProtocol
    from ludamus.pacts.venues import PrintScopeOptionDTO


class PanelRequest(HttpRequest):
    """Request type for panel views with UoW and context."""

    context: AuthenticatedRequestContext
    di: DependencyInjectorProtocol
    services: ServicesProtocol


class PanelAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin to require panel access (sphere manager only)."""

    request: PanelRequest

    def test_func(self) -> bool:
        """Check if user is a sphere manager.

        Returns:
            True if user is a manager of the current sphere, False otherwise.
        """
        # LoginRequiredMixin ensures user is authenticated before this is called
        current_sphere_id = self.request.context.current_sphere_id
        user_slug = self.request.context.current_user_slug
        return self.request.di.uow.spheres.is_manager(current_sphere_id, user_slug)

    def handle_no_permission(self) -> HttpResponseRedirect:
        """Handle no permission based on authentication status.

        Returns:
            Redirect response to login page for anonymous users,
            or to web:index with error message for authenticated users.
        """
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()

        messages.error(
            self.request, _("You don't have permission to access the backoffice panel.")
        )
        return redirect("web:index")


class EventContextMixin:
    """Mixin providing common event context for panel views."""

    request: PanelRequest

    def get_event_context(self, slug: str) -> tuple[dict[str, Any], EventDTO | None]:
        """Build common context for event pages.

        Returns:
            Tuple of (context dict, current_event or None if not found).
        """
        sphere_id = self.request.context.current_sphere_id
        events = self.request.di.uow.events.list_by_sphere(sphere_id)

        try:
            current_event = self.request.di.uow.events.read_by_slug(slug, sphere_id)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return {}, None

        panel_service = PanelService(self.request.di.uow)
        stats = panel_service.get_event_stats(current_event.pk)

        context: dict[str, Any] = {
            "events": events,
            "current_event": current_event,
            "is_proposal_active": is_proposal_active(current_event),
            "stats": stats.model_dump(),
        }

        return context, current_event

    def get_current_event(self, slug: str) -> EventDTO | None:
        return self.get_event_context(slug)[1]

    def get_track_filter_context(
        self, event_pk: int
    ) -> tuple[list[Any], set[int], int | None]:
        """Return track filter context tuple for track switcher.

        Auto-selects a single managed track when track GET param is absent.

        Returns:
            Tuple of (sorted_tracks, managed_track_pks, filter_track_pk).
        """
        all_tracks = self.request.di.uow.tracks.list_by_event(event_pk)
        managed_tracks = self.request.di.uow.tracks.list_by_manager(
            self.request.context.current_user_id, event_pk=event_pk
        )
        managed_pks = {t.pk for t in managed_tracks}

        track_param = self.request.GET.get("track", "").strip()
        if "track" not in self.request.GET and len(managed_tracks) == 1:
            filter_track_pk: int | None = managed_tracks[0].pk
        elif track_param.isdigit():
            filter_track_pk = int(track_param)
        else:
            filter_track_pk = None

        sorted_tracks = sorted(
            all_tracks, key=lambda t: (t.pk not in managed_pks, t.name)
        )
        return sorted_tracks, managed_pks, filter_track_pk

    def get_print_scopes(self, event_pk: int) -> list[PrintScopeOptionDTO]:
        # Non-leaf tree nodes selectable as print scopes.
        return self.request.services.venues.list_print_scopes(event_pk)


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


def cfp_tab_urls(slug: str) -> dict[str, str]:
    return {
        "types": reverse("panel:cfp", kwargs={"slug": slug}),
        "host": reverse("panel:personal-data-fields", kwargs={"slug": slug}),
        "session": reverse("panel:session-fields", kwargs={"slug": slug}),
        "time_slots": reverse("panel:time-slots", kwargs={"slug": slug}),
    }


def facilitator_tab_urls(slug: str) -> dict[str, str]:
    return {
        "list": reverse("panel:facilitators", kwargs={"slug": slug}),
        "merge": reverse("panel:facilitator-merge", kwargs={"slug": slug}),
        "columns": reverse("panel:facilitator-columns", kwargs={"slug": slug}),
    }


def import_tab_urls(slug: str, pk: int) -> dict[str, str]:
    return {
        "proposal": reverse(
            "panel:import-integration", kwargs={"slug": slug, "pk": pk}
        ),
        "review": reverse("panel:import-review", kwargs={"slug": slug, "pk": pk}),
        "json": reverse("panel:import-json", kwargs={"slug": slug, "pk": pk}),
        "run": reverse("panel:import-run", kwargs={"slug": slug, "pk": pk}),
        "log": reverse("panel:import-log", kwargs={"slug": slug, "pk": pk}),
    }


# Cap the base at 45 so neither it nor a "-XXXX" retry suffix overflows the
# SlugField() varchar(50) column — Postgres raises DataError on overflow, SQLite
# ignores the limit, so an over-long title 500s only in production.
_SLUG_BASE_MAX_LENGTH = 45


def make_unique_slug(
    *, name: str, default: str, check_exists: Callable[[str], bool]
) -> str:
    # Cap after the fallback so an over-long default can't overflow either.
    base_slug = (slugify(name) or default)[:_SLUG_BASE_MAX_LENGTH]
    slug = base_slug
    for _attempt in range(4):
        if not check_exists(slug):
            break
        slug = f"{base_slug}-{token_urlsafe(3)}"
    return slug
