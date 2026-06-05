from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, ClassVar

from django.http import Http404, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.utils.timezone import get_current_timezone, localtime, make_aware
from django.views.generic.base import View

from ludamus.mills.qr import qr_svg
from ludamus.pacts import NotFoundError
from ludamus.pacts.printing import AreaScheduleQueryDTO, PrintTimetableQueryDTO

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO
    from ludamus.pacts.printing import PrintOptionDTO, PrintSpaceOptionDTO


def _is_manager(request: RootRequest) -> bool:
    return (
        request.user.is_authenticated
        and request.context.current_user_slug is not None
        and request.di.uow.spheres.is_manager(
            request.context.current_sphere_id, request.context.current_user_slug
        )
    )


class PublicEventPrintView(View):
    request: RootRequest
    template_name = "chronology/print.html"
    DEFAULT_RANGE_HOURS = 6
    MAX_RANGE_HOURS = 72
    MATERIAL_AREA_DESCRIPTIONS = "area-descriptions"
    MATERIAL_AREA_TIMETABLE = "area-timetable"
    MATERIAL_SPACE_TIMETABLE = "space-timetable"
    MATERIAL_VENUE_TIMETABLE = "venue-timetable"
    MATERIAL_TRACK_TIMETABLE = "track-timetable"
    MATERIAL_EVENT_TIMETABLE = "event-timetable"
    MATERIAL_SESSION_LIST = "session-list"
    MATERIALS: ClassVar[set[str]] = {
        MATERIAL_AREA_DESCRIPTIONS,
        MATERIAL_AREA_TIMETABLE,
        MATERIAL_SPACE_TIMETABLE,
        MATERIAL_VENUE_TIMETABLE,
        MATERIAL_TRACK_TIMETABLE,
        MATERIAL_EVENT_TIMETABLE,
        MATERIAL_SESSION_LIST,
    }

    def get(self, request: RootRequest, slug: str) -> HttpResponse:
        try:
            event = request.services.events.read_by_slug(
                slug, request.context.current_sphere_id
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
        session_list_available = session_list_candidate is not None
        available_materials = self._available_materials(
            session_list_available=session_list_available
        )
        material = self._resolve_material(available_materials)

        timetable = None
        area_schedule = None
        session_list = None
        if material == self.MATERIAL_AREA_DESCRIPTIONS:
            area_schedule = service.build_area_schedule(
                AreaScheduleQueryDTO(
                    event_pk=event.pk,
                    time_range=(range_start, range_end),
                    area_pks=scope.area_pks,
                    scope_name=scope.scope_name,
                    confirmed_only=True,
                )
            )
        elif material == self.MATERIAL_SESSION_LIST:
            session_list = session_list_candidate
        else:
            timetable = service.build_timetable(
                PrintTimetableQueryDTO(
                    event_pk=event.pk,
                    tz=tz,
                    area_pks=self._timetable_area_pks(material, scope.area_pks),
                    space_pks=self._space_pks(material, selected_space_pk),
                    track_pk=self._track_pk(material, selected_track),
                    scope_name=self._timetable_scope_name(
                        material, scope.scope_name, space_scope_name, selected_track
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
                "session_list_available": session_list_available,
                "material": material,
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

    def _available_materials(self, *, session_list_available: bool) -> set[str]:
        materials = set(self.MATERIALS)
        if not session_list_available:
            materials.remove(self.MATERIAL_SESSION_LIST)
        return materials

    def _resolve_material(self, available_materials: set[str]) -> str:
        raw_material = self.request.GET.get("material")
        if raw_material:
            material = raw_material
        elif self.request.GET.get("area"):
            material = self.MATERIAL_AREA_TIMETABLE
        elif self.request.GET.get("venue"):
            material = self.MATERIAL_VENUE_TIMETABLE
        else:
            material = self.MATERIAL_EVENT_TIMETABLE
        if material in available_materials:
            return material
        return self.MATERIAL_EVENT_TIMETABLE

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
        slug = self.request.GET.get("track") or ""
        if slug:
            return next((track for track in tracks if track.slug == slug), None)
        return tracks[0] if tracks else None

    def _space_pks(
        self, material: str, selected_space_pk: int | None
    ) -> frozenset[int] | None:
        if material != self.MATERIAL_SPACE_TIMETABLE or selected_space_pk is None:
            return None
        return frozenset({selected_space_pk})

    def _track_pk(self, material: str, track: PrintOptionDTO | None) -> int | None:
        if material != self.MATERIAL_TRACK_TIMETABLE or track is None:
            return None
        return track.pk

    def _timetable_area_pks(
        self, material: str, area_pks: frozenset[int] | None
    ) -> frozenset[int] | None:
        if material not in {
            self.MATERIAL_AREA_TIMETABLE,
            self.MATERIAL_VENUE_TIMETABLE,
        }:
            return None
        return area_pks

    def _timetable_scope_name(
        self,
        material: str,
        scope_name: str | None,
        space_scope_name: str | None,
        track: PrintOptionDTO | None,
    ) -> str | None:
        if material == self.MATERIAL_SPACE_TIMETABLE:
            return space_scope_name
        if material == self.MATERIAL_TRACK_TIMETABLE:
            return track.name if track else None
        if material in {self.MATERIAL_AREA_TIMETABLE, self.MATERIAL_VENUE_TIMETABLE}:
            return scope_name
        return None
