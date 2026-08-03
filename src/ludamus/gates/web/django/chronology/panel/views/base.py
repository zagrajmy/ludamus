"""Shared mixins, request type, and helpers for panel views."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any

from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin as EventPanelContextMixin,
)
from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ludamus.pacts import DependencyInjectorProtocol, FacilitatorListItemDTO
    from ludamus.pacts.submissions import (
        FacilitatorColumnDTO,
        FacilitatorPanelServiceProtocol,
    )


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


def _format_field_value(*, value: str | list[str] | bool | None) -> str:
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, list):
        return ", ".join(value)
    return value or ""


def _builtin_cell(*, key: str, facilitator: FacilitatorListItemDTO) -> str:
    if key == "name":
        return facilitator.display_name
    if key == "linked":
        return _("Linked") if facilitator.user_id else _("None")
    if key == "sessions":
        return str(facilitator.session_count)
    if key == "organizer":
        return facilitator.organizer_name or "—"
    return str(
        ACCREDITATION_TYPE_LABELS[AccreditationType(facilitator.accreditation_type)]
    )


def build_column_values(
    *,
    panel: FacilitatorPanelServiceProtocol,
    facilitators: Sequence[FacilitatorListItemDTO],
    columns: Sequence[FacilitatorColumnDTO],
) -> dict[int, dict[str, str]]:
    raw_values = panel.column_values(
        facilitator_ids=[f.pk for f in facilitators],
        field_ids=[column.field.pk for column in columns if column.field is not None],
    )
    # One ready-to-render string per (facilitator, column), so the template
    # renders every column the same way whatever the organizer chose. Lives
    # here rather than on either page because the facilitator list and the
    # timetable's facilitator picker both render these cells.
    return {
        facilitator.pk: {
            column.key: (
                _format_field_value(
                    value=raw_values.get(facilitator.pk, {}).get(column.field.slug)
                )
                if column.field is not None
                else _builtin_cell(key=column.key, facilitator=facilitator)
            )
            for column in columns
        }
        for facilitator in facilitators
    }
