"""Shared mixins, request type, and helpers for panel views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Page, Paginator
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from ludamus.gates.web.django.access import has_panel_access
from ludamus.mills import PanelService, is_proposal_active
from ludamus.pacts import DependencyInjectorProtocol, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import AuthenticatedRequestContext, EventDTO
    from ludamus.pacts.services import ServicesProtocol
    from ludamus.pacts.venues import PrintScopeOptionDTO


PAGE_SIZES = (10, 20, 50, 100)
DEFAULT_PAGE_SIZE = 20


def paginate[T](request: HttpRequest, items: Sequence[T]) -> Page[T]:
    raw = request.GET.get("page_size", "")
    size = int(raw) if raw.isdigit() and int(raw) in PAGE_SIZES else DEFAULT_PAGE_SIZE
    return Paginator(items, size).get_page(request.GET.get("page"))


def pagination_context[T](request: HttpRequest, items: Sequence[T]) -> dict[str, Any]:
    # The sizes travel with the page so the picker can't drift from the
    # sizes `paginate` actually honours.
    page_obj = paginate(request, items)
    return {"page_obj": page_obj, "page_sizes": list(PAGE_SIZES)}


def safe_next_url(request: HttpRequest, fallback: str) -> str:
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return fallback


def format_field_value(*, value: str | list[str] | bool | None) -> str:
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, list):
        return ", ".join(value)
    return value or ""


class PanelRequest(HttpRequest):
    """Request type for panel views with UoW and context."""

    context: AuthenticatedRequestContext
    di: DependencyInjectorProtocol
    services: ServicesProtocol


class PanelAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    request: PanelRequest

    def test_func(self) -> bool:
        return has_panel_access(self.request)

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


def proposal_tab_urls(slug: str) -> dict[str, str]:
    return {
        "list": reverse("panel:proposals", kwargs={"slug": slug}),
        "columns": reverse("panel:proposal-columns", kwargs={"slug": slug}),
    }


def proposal_detail_tab_urls(slug: str, proposal_id: int) -> dict[str, str]:
    kwargs = {"slug": slug, "proposal_id": proposal_id}
    return {
        "details": reverse("panel:proposal-detail", kwargs=kwargs),
        "history": reverse("panel:proposal-history", kwargs=kwargs),
    }


def facilitator_detail_tab_urls(slug: str, facilitator_slug: str) -> dict[str, str]:
    kwargs = {"slug": slug, "facilitator_slug": facilitator_slug}
    return {
        "details": reverse("panel:facilitator-detail", kwargs=kwargs),
        "history": reverse("panel:facilitator-history", kwargs=kwargs),
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
