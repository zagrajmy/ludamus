from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Literal

from django.http import Http404, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.dateparse import parse_datetime
from django.utils.timezone import get_current_timezone, localtime, make_aware
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import View

from ludamus.mills.qr import qr_svg
from ludamus.pacts import NotFoundError
from ludamus.pacts.printing import AreaScheduleQueryDTO, PrintTimetableQueryDTO

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO
    from ludamus.pacts.printing import PrintOptionDTO

    type _LazyStr = str | _StrPromise


DocumentKind = Literal["area_schedule", "session_list", "timetable"]
ScopeKind = Literal["event", "scope", "track"]


@dataclass(frozen=True)
class MaterialSpec:
    value: str
    label: _LazyStr
    document_kind: DocumentKind
    scope_kind: ScopeKind = "event"
    requires_session_list: bool = False

    # The sidebar controls a material exposes follow directly from its scope, so
    # they are derived rather than stored (keeps the specs from drifting).
    @property
    def show_scope_control(self) -> bool:
        return self.scope_kind == "scope"

    @property
    def show_track_control(self) -> bool:
        return self.scope_kind == "track"

    @property
    def show_range_controls(self) -> bool:
        return self.document_kind == "area_schedule"


TIMETABLE = "timetable"
TIMETABLE_DESCRIPTIONS = "timetable-descriptions"
TRACK_TIMETABLE = "track-timetable"
SESSION_LIST = "session-list"
# One timetable material, scopable to any space-tree node (a single room, a
# whole floor, a building) or left unscoped for the whole event — the Scope
# picker covers every level, so there is no separate venue/area/space material.
MATERIAL_SPECS = (
    MaterialSpec(TIMETABLE, _("Timetable"), "timetable", scope_kind="scope"),
    MaterialSpec(
        TIMETABLE_DESCRIPTIONS,
        _("Timetable with descriptions"),
        "area_schedule",
        scope_kind="scope",
    ),
    MaterialSpec(
        TRACK_TIMETABLE, _("Track timetable"), "timetable", scope_kind="track"
    ),
    MaterialSpec(
        SESSION_LIST, _("Session list"), "session_list", requires_session_list=True
    ),
)
MATERIAL_SPECS_BY_VALUE = {spec.value: spec for spec in MATERIAL_SPECS}


def _is_manager(request: RootRequest) -> bool:
    user_slug = request.context.current_user_slug
    return (
        request.user.is_authenticated
        and user_slug is not None
        and request.services.sphere_panel.is_manager(
            request.context.current_sphere_id, user_slug
        )
    )


def _available_materials(
    *, session_list_available: bool, tracks_available: bool
) -> tuple[MaterialSpec, ...]:
    return tuple(
        spec
        for spec in MATERIAL_SPECS
        if (session_list_available or not spec.requires_session_list)
        and (tracks_available or spec.scope_kind != "track")
    )


def _track_pk(material: MaterialSpec, track: PrintOptionDTO | None) -> int | None:
    if material.scope_kind != "track" or track is None:
        return None
    return track.pk


def _scope_pk(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _timetable_scope_pks(
    material: MaterialSpec, scope_space_pks: frozenset[int] | None
) -> frozenset[int] | None:
    if material.scope_kind != "scope":
        return None
    return scope_space_pks


def _timetable_scope_name(
    material: MaterialSpec, scope_name: str | None, track: PrintOptionDTO | None
) -> str | None:
    if material.scope_kind == "track":
        return track.name if track else None
    if material.scope_kind == "scope":
        return scope_name
    return None


class PublicEventPrintView(View):
    request: RootRequest
    template_name = "chronology/print.html"
    DEFAULT_RANGE_HOURS = 6
    MAX_RANGE_HOURS = 72

    def get(self, request: RootRequest, slug: str) -> HttpResponse:
        try:
            event = request.services.events.read_by_slug(
                request.context.current_sphere_id, slug
            )
        except NotFoundError as exc:
            raise Http404 from exc

        published = (
            event.publication_time is not None
            and event.publication_time <= datetime.now(tz=UTC)
        )
        if not published and not _is_manager(request):
            raise Http404

        scope_pk = _scope_pk(request.GET.get("scope"))
        try:
            scope = request.services.venues.resolve_scope(event.pk, scope_pk)
        except NotFoundError as exc:
            raise Http404 from exc

        tz = get_current_timezone()
        range_start, range_hours = self._resolve_range(event, tz)
        range_end = range_start + timedelta(hours=range_hours)

        service = request.services.print_materials
        tracks = service.list_tracks(event.pk)
        selected_track = self._selected_track(tracks)
        session_list_candidate = service.build_session_list(
            event.pk, confirmed_only=True
        )
        material_options = _available_materials(
            session_list_available=session_list_candidate is not None,
            tracks_available=bool(tracks),
        )
        material_spec = self._resolve_material(material_options)

        timetable = None
        area_schedule = None
        session_list = None
        if material_spec.document_kind == "area_schedule":
            area_schedule = service.build_area_schedule(
                AreaScheduleQueryDTO(
                    event_pk=event.pk,
                    time_range=(range_start, range_end),
                    scope_space_pks=scope.space_pks,
                    scope_name=scope.scope_name,
                    confirmed_only=True,
                )
            )
        elif material_spec.document_kind == "session_list":
            session_list = session_list_candidate
        else:
            timetable = service.build_timetable(
                PrintTimetableQueryDTO(
                    event_pk=event.pk,
                    tz=tz,
                    scope_space_pks=_timetable_scope_pks(
                        material_spec, scope.space_pks
                    ),
                    track_pk=_track_pk(material_spec, selected_track),
                    scope_name=_timetable_scope_name(
                        material_spec, scope.scope_name, selected_track
                    ),
                    confirmed_only=True,
                )
            )

        event_url = request.build_absolute_uri(
            reverse("web:chronology:event", kwargs={"slug": slug})
        )
        sphere = request.services.sphere_panel.read(request.context.current_sphere_id)

        response = TemplateResponse(
            request,
            self.template_name,
            {
                "event": event,
                "logo": event.logo or sphere.logo,
                "timetable": timetable,
                "area_schedule": area_schedule,
                "session_list": session_list,
                "qr_svg": qr_svg(event_url, xmldecl=False),
                "print_scopes": request.services.venues.list_print_scopes(event.pk),
                "tracks": tracks,
                "material_options": material_options,
                "material": material_spec.value,
                "show_scope_control": material_spec.show_scope_control,
                "show_track_control": material_spec.show_track_control,
                "show_range_controls": material_spec.show_range_controls,
                "selected_scope": str(scope_pk) if scope_pk is not None else "",
                "selected_track": selected_track.slug if selected_track else "",
                "range_start_value": (
                    localtime(range_start, tz).strftime("%Y-%m-%dT%H:%M")
                ),
                "range_hours": range_hours,
            },
        )
        if published:
            patch_cache_control(response, public=True, max_age=300)
        else:
            patch_cache_control(response, private=True, max_age=5)
        return response

    def _resolve_material(
        self, available_materials: tuple[MaterialSpec, ...]
    ) -> MaterialSpec:
        # The timetable is the default; it carries the Scope picker, so a scoped
        # request needs no special-casing here.
        available_by_value = {spec.value: spec for spec in available_materials}
        material = MATERIAL_SPECS_BY_VALUE.get(self.request.GET.get("material") or "")
        if material and material.value in available_by_value:
            return material
        return MATERIAL_SPECS_BY_VALUE[TIMETABLE]

    def _resolve_range(self, event: EventDTO, tz: tzinfo) -> tuple[datetime, int]:
        hours = self.DEFAULT_RANGE_HOURS
        with suppress(ValueError, TypeError):
            hours = int(self.request.GET.get("hours", self.DEFAULT_RANGE_HOURS))
        hours = max(1, min(hours, self.MAX_RANGE_HOURS))

        start = localtime(event.start_time, tz)
        if raw_start := self.request.GET.get("start"):
            with suppress(ValueError):
                if (parsed := parse_datetime(raw_start)) is not None:
                    start = parsed if parsed.tzinfo else make_aware(parsed, tz)
        return start, hours

    def _selected_track(self, tracks: list[PrintOptionDTO]) -> PrintOptionDTO | None:
        if slug := self.request.GET.get("track") or "":
            # A stale/invalid slug must not silently print the whole event; fall
            # back to the first track.
            selected = next((track for track in tracks if track.slug == slug), None)
            if selected is not None:
                return selected
        return tracks[0] if tracks else None
