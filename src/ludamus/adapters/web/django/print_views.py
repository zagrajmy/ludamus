from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Literal

from django.http import Http404, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
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
    from ludamus.pacts.printing import PrintOptionDTO, PrintSpaceOptionDTO

    type _LazyStr = str | _StrPromise


DocumentKind = Literal["area_schedule", "session_list", "timetable"]
ScopeKind = Literal["event", "area", "space", "track"]


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
        return self.scope_kind == "area"

    @property
    def show_space_control(self) -> bool:
        return self.scope_kind == "space"

    @property
    def show_track_control(self) -> bool:
        return self.scope_kind == "track"

    @property
    def show_range_controls(self) -> bool:
        return self.document_kind == "area_schedule"


AREA_DESCRIPTIONS = "area-descriptions"
AREA_TIMETABLE = "area-timetable"
SPACE_TIMETABLE = "space-timetable"
VENUE_TIMETABLE = "venue-timetable"
TRACK_TIMETABLE = "track-timetable"
EVENT_TIMETABLE = "event-timetable"
SESSION_LIST = "session-list"
MATERIAL_SPECS = (
    MaterialSpec(
        AREA_DESCRIPTIONS,
        _("Area with descriptions"),
        "area_schedule",
        scope_kind="area",
    ),
    MaterialSpec(AREA_TIMETABLE, _("Area timetable"), "timetable", scope_kind="area"),
    MaterialSpec(
        SPACE_TIMETABLE, _("Space timetable"), "timetable", scope_kind="space"
    ),
    MaterialSpec(VENUE_TIMETABLE, _("Venue timetable"), "timetable", scope_kind="area"),
    MaterialSpec(
        TRACK_TIMETABLE, _("Track timetable"), "timetable", scope_kind="track"
    ),
    MaterialSpec(EVENT_TIMETABLE, _("Event timetable"), "timetable"),
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


def _space_pks(
    material: MaterialSpec, selected_space_pk: int | None
) -> frozenset[int] | None:
    if material.scope_kind != "space" or selected_space_pk is None:
        return None
    return frozenset({selected_space_pk})


def _track_pk(material: MaterialSpec, track: PrintOptionDTO | None) -> int | None:
    if material.scope_kind != "track" or track is None:
        return None
    return track.pk


def _timetable_area_pks(
    material: MaterialSpec, area_pks: frozenset[int] | None
) -> frozenset[int] | None:
    if material.scope_kind != "area":
        return None
    return area_pks


def _timetable_scope_name(
    material: MaterialSpec,
    scope_name: str | None,
    space_scope_name: str | None,
    track: PrintOptionDTO | None,
) -> str | None:
    if material.scope_kind == "space":
        return space_scope_name
    if material.scope_kind == "track":
        return track.name if track else None
    if material.scope_kind == "area":
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

        try:
            scope = request.services.venues.resolve_scope(
                event.pk,
                request.GET.get("venue") or None,
                request.GET.get("area") or None,
            )
        except NotFoundError as exc:
            raise Http404 from exc

        tz = get_current_timezone()
        range_start, range_hours = self._resolve_range(event, tz)
        range_end = range_start + timedelta(hours=range_hours)

        service = request.services.print_materials
        spaces = service.list_spaces(event.pk)
        selected_space_pk = self._selected_space_pk(spaces)
        space_scope_name = next(
            (space.name for space in spaces if space.pk == selected_space_pk), None
        )

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
                    area_pks=scope.area_pks,
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
                    area_pks=_timetable_area_pks(material_spec, scope.area_pks),
                    space_pks=_space_pks(material_spec, selected_space_pk),
                    track_pk=_track_pk(material_spec, selected_track),
                    scope_name=_timetable_scope_name(
                        material_spec,
                        scope.scope_name,
                        space_scope_name,
                        selected_track,
                    ),
                    confirmed_only=True,
                )
            )

        event_url = request.build_absolute_uri(
            reverse("web:chronology:event", kwargs={"slug": slug})
        )
        sphere = request.services.sphere_panel.read(request.context.current_sphere_id)

        return TemplateResponse(
            request,
            self.template_name,
            {
                "event": event,
                "logo": event.logo or sphere.logo,
                "timetable": timetable,
                "area_schedule": area_schedule,
                "session_list": session_list,
                "qr_svg": qr_svg(event_url, xmldecl=False),
                "venues": request.services.venues.list_with_areas(event.pk),
                "spaces": spaces,
                "tracks": tracks,
                "material_options": material_options,
                "material": material_spec.value,
                "show_scope_control": material_spec.show_scope_control,
                "show_space_control": material_spec.show_space_control,
                "show_track_control": material_spec.show_track_control,
                "show_range_controls": material_spec.show_range_controls,
                "selected_venue": request.GET.get("venue") or "",
                "selected_area": request.GET.get("area") or "",
                "selected_space": str(selected_space_pk or ""),
                "selected_track": selected_track.slug if selected_track else "",
                "range_start_value": (
                    localtime(range_start, tz).strftime("%Y-%m-%dT%H:%M")
                ),
                "range_hours": range_hours,
            },
        )

    def _resolve_material(
        self, available_materials: tuple[MaterialSpec, ...]
    ) -> MaterialSpec:
        available_by_value = {spec.value: spec for spec in available_materials}
        if raw_material := self.request.GET.get("material"):
            material = MATERIAL_SPECS_BY_VALUE.get(raw_material)
        elif self.request.GET.get("area"):
            material = MATERIAL_SPECS_BY_VALUE[AREA_TIMETABLE]
        elif self.request.GET.get("venue"):
            material = MATERIAL_SPECS_BY_VALUE[VENUE_TIMETABLE]
        else:
            material = MATERIAL_SPECS_BY_VALUE[EVENT_TIMETABLE]
        if material and material.value in available_by_value:
            return material
        return MATERIAL_SPECS_BY_VALUE[EVENT_TIMETABLE]

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

    def _selected_space_pk(self, spaces: list[PrintSpaceOptionDTO]) -> int | None:
        raw = self.request.GET.get("space") or ""
        with suppress(ValueError):
            selected = int(raw)
            if any(space.pk == selected for space in spaces):
                return selected
        return spaces[0].pk if spaces else None

    def _selected_track(self, tracks: list[PrintOptionDTO]) -> PrintOptionDTO | None:
        if slug := self.request.GET.get("track") or "":
            # A stale/invalid slug must not silently print the whole event; fall
            # back to the first track, mirroring `_selected_space_pk`.
            selected = next((track for track in tracks if track.slug == slug), None)
            if selected is not None:
                return selected
        return tracks[0] if tracks else None
