"""Shared mixins, request type, and helpers for panel views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.paginator import Page, Paginator
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin as EventPanelContextMixin,
)
from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelAccessMixin,
    EventPanelRequest,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.http import HttpRequest

    from ludamus.pacts import DependencyInjectorProtocol


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
    # Actions post it, links carry it in the query — both spellings mean "the
    # list the organizer came from", filters and all.
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return fallback


def back_to_proposals(request: HttpRequest, slug: str) -> str:
    return safe_next_url(request, reverse("panel:proposals", kwargs={"slug": slug}))


def proposal_detail_url(*, request: HttpRequest, slug: str, proposal_id: int) -> str:
    # A bare proposals URL means the pending backlog, so the detail page has to
    # keep carrying the query the organizer arrived with.
    detail = reverse(
        "panel:proposal-detail", kwargs={"slug": slug, "proposal_id": proposal_id}
    )
    back = safe_next_url(request, "")
    return f"{detail}?{urlencode({'next': back})}" if back else detail


def format_field_value(
    *, value: str | list[str] | bool | None, labels: Mapping[str, str] | None = None
) -> str:
    # A stored answer holds option *values*; pass `labels` where the reader
    # should see the option labels instead, and a checkbox as a word rather
    # than "True".
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    by_value = labels or {}
    if isinstance(value, list):
        return ", ".join(by_value.get(item) or item for item in value)
    return by_value.get(value or "") or value or ""


class PanelRequest(EventPanelRequest):
    """Request type for panel views with UoW and context."""

    di: DependencyInjectorProtocol


class PanelAccessMixin(EventPanelAccessMixin):
    request: PanelRequest


class EventContextMixin(EventPanelContextMixin):
    """Adds the legacy UoW-backed helpers to the shared event context mixin."""

    request: PanelRequest

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
