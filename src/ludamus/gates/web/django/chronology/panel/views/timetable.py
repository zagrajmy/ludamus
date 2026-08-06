"""Timetable panel views."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.http import HttpResponse, QueryDict
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.timezone import get_current_timezone
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.mills.timetable import (
    ConflictDetectionService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.pacts import (
    UNSCHEDULED_LIST_LIMIT,
    NotFoundError,
    UnscheduledSessionFilter,
)
from ludamus.pacts.chronology import DateSelection, SessionPlacement

if TYPE_CHECKING:
    from ludamus.pacts.legacy import TrackDTO


def _parse_iso_duration_minutes(iso: str) -> int:
    if not (match := re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso)):
        return 60
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes


def timetable_tab_urls(slug: str) -> dict[str, str]:
    return {
        "timetable": reverse("panel:timetable", kwargs={"slug": slug}),
        "log": reverse("panel:timetable-log", kwargs={"slug": slug}),
        "overview": reverse("panel:timetable-overview", kwargs={"slug": slug}),
        "problems": reverse("panel:timetable-problems", kwargs={"slug": slug}),
        "confirmations": reverse(
            "panel:timetable-confirmations", kwargs={"slug": slug}
        ),
    }


_BACK_URL_KEYS = ("track", "category", "max_duration", "search", "date")


def _build_back_url(slug: str, query: QueryDict) -> str:
    base = reverse("panel:timetable-browse-pane-part", kwargs={"slug": slug})
    params = [(key, query[key]) for key in _BACK_URL_KEYS if query.get(key, "").strip()]
    return f"{base}?{urlencode(params)}" if params else base


def _print_url(
    *,
    slug: str,
    tracks: list[TrackDTO],
    track_pk: int | None,
    date_selection: DateSelection,
) -> str:
    # The print page is preset to the schedule's current view: an active track
    # filter prints that track, a picked day prints that day — the filters the
    # organizer already dialed in aren't wasted.
    params: list[tuple[str, str]] = []
    if (track := next((t for t in tracks if t.pk == track_pk), None)) is not None:
        params += [("material", "track-timetable"), ("track", track.slug)]
    if date_selection != "all":
        params += [("start", f"{date_selection.isoformat()}T00:00"), ("hours", "24")]
    base = reverse("web:chronology:event-print", kwargs={"slug": slug})
    return f"{base}?{urlencode(params)}" if params else base


def _parse_date_selection(raw: str | None) -> DateSelection:
    if raw == "all":
        return "all"
    if not raw:
        return "all"
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return "all"


class TimetablePageView(PanelAccessMixin, EventContextMixin, View):
    """Static timetable grid for a specific event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "timetable"

        sorted_tracks, managed_pks, filter_track_pk = self.get_track_filter_context(
            current_event.pk
        )

        try:
            room_page = int(self.request.GET.get("room_page", "1"))
        except ValueError:
            room_page = 1

        date_selection = _parse_date_selection(self.request.GET.get("date"))

        category_pk_raw = self.request.GET.get("category", "").strip()
        category_pk = int(category_pk_raw) if category_pk_raw.isdigit() else None
        max_dur_raw = self.request.GET.get("max_duration", "").strip()
        max_duration_minutes = int(max_dur_raw) if max_dur_raw.isdigit() else None

        uow = self.request.di.uow
        grid = TimetableService(uow).build_grid(
            event_pk=current_event.pk,
            tz=get_current_timezone(),
            track_pk=filter_track_pk,
            space_page=room_page,
            date_selection=date_selection,
        )
        categories = uow.proposal_categories.list_by_event(current_event.pk)

        context["all_tracks"] = sorted_tracks
        context["managed_track_pks"] = managed_pks
        context["filter_track_pk"] = filter_track_pk
        context["room_page"] = room_page
        context["grid"] = grid
        context["conflicts"] = grid.conflicts
        context["conflicts_count"] = len(grid.conflicts)
        context["categories"] = categories
        context["category_pk"] = category_pk
        context["max_duration_minutes"] = max_duration_minutes
        context["duration_chips"] = [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)]
        context["date_selection"] = grid.date_selection
        context["slug"] = slug
        context["tab_urls"] = timetable_tab_urls(slug)
        context["active_tab"] = "timetable"
        context["print_url"] = _print_url(
            slug=slug,
            tracks=sorted_tracks,
            track_pk=filter_track_pk,
            date_selection=grid.date_selection,
        )
        return TemplateResponse(self.request, "panel/timetable.html", context)


class TimetableSessionListPartView(PanelAccessMixin, EventContextMixin, View):
    """HTMX partial: unscheduled session list for the left pane."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        _, _, filter_track_pk = self.get_track_filter_context(current_event.pk)

        search = self.request.GET.get("search", "").strip() or None
        category_pk_raw = self.request.GET.get("category", "").strip()
        category_pk = int(category_pk_raw) if category_pk_raw.isdigit() else None
        max_dur_raw = self.request.GET.get("max_duration", "").strip()
        max_duration_minutes = int(max_dur_raw) if max_dur_raw.isdigit() else None
        date_selection = _parse_date_selection(self.request.GET.get("date"))

        uow = self.request.di.uow
        sessions, has_more = uow.sessions.list_unscheduled_by_event(
            current_event.pk,
            UnscheduledSessionFilter(
                track_pk=filter_track_pk,
                search=search,
                max_duration_minutes=max_duration_minutes,
                category_pk=category_pk,
                available_on=(
                    date_selection if isinstance(date_selection, date) else None
                ),
            ),
        )
        categories = uow.proposal_categories.list_by_event(current_event.pk)

        duration_chips = [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)]

        context = {
            "sessions": sessions,
            "has_more": has_more,
            "limit": UNSCHEDULED_LIST_LIMIT,
            "categories": categories,
            "search": search or "",
            "category_pk": category_pk,
            "max_duration_minutes": max_duration_minutes,
            "duration_chips": duration_chips,
            "filter_track_pk": filter_track_pk,
            "date_selection": date_selection,
            "slug": slug,
        }
        return TemplateResponse(
            self.request, "panel/parts/timetable-session-list.html", context
        )


class TimetableBrowsePanePartView(PanelAccessMixin, EventContextMixin, View):
    """HTMX partial: full browse-mode left pane (search + initial session list)."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        _, _, filter_track_pk = self.get_track_filter_context(current_event.pk)

        category_pk_raw = self.request.GET.get("category", "").strip()
        category_pk = int(category_pk_raw) if category_pk_raw.isdigit() else None
        max_dur_raw = self.request.GET.get("max_duration", "").strip()
        max_duration_minutes = int(max_dur_raw) if max_dur_raw.isdigit() else None
        search = self.request.GET.get("search", "").strip()
        date_selection = _parse_date_selection(self.request.GET.get("date"))

        context = {
            "filter_track_pk": filter_track_pk,
            "category_pk": category_pk,
            "max_duration_minutes": max_duration_minutes,
            "search": search,
            "date_selection": date_selection,
            "slug": slug,
            "current_event": current_event,
        }
        return TemplateResponse(
            self.request, "panel/parts/timetable-browse-pane.html", context
        )


class TimetableSessionDetailPartView(PanelAccessMixin, EventContextMixin, View):
    """HTMX partial: session detail in the left pane."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        uow = self.request.di.uow
        try:
            session = uow.sessions.read(pk)
        except NotFoundError:
            return redirect("panel:timetable", slug=slug)

        session_event = uow.sessions.read_event(pk)
        if session_event.pk != current_event.pk:
            return redirect("panel:timetable", slug=slug)

        agenda_item = uow.agenda_items.read_by_session(pk)
        facilitators = uow.sessions.read_facilitators(pk)
        time_slots = uow.sessions.read_preferred_time_slots(pk)

        duration_minutes = _parse_iso_duration_minutes(session.duration)

        back_url = _build_back_url(slug, self.request.GET)

        time_slots_json = json.dumps(
            [
                {"start": s.start_time.isoformat(), "end": s.end_time.isoformat()}
                for s in time_slots
            ]
        )

        context = {
            "session": session,
            "agenda_item": agenda_item,
            "facilitators": facilitators,
            "time_slots": time_slots,
            "time_slots_json": time_slots_json,
            "duration_minutes": duration_minutes,
            "slug": slug,
            "event": current_event,
            "back_url": back_url,
        }
        return TemplateResponse(
            self.request, "panel/parts/timetable-session-detail.html", context
        )


class TimetableGridPartView(PanelAccessMixin, EventContextMixin, View):
    """HTMX partial: timetable grid refresh."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        _, _, filter_track_pk = self.get_track_filter_context(current_event.pk)

        try:
            room_page = int(self.request.GET.get("room_page", "1"))
        except ValueError:
            room_page = 1

        date_selection = _parse_date_selection(self.request.GET.get("date"))

        grid = TimetableService(self.request.di.uow).build_grid(
            event_pk=current_event.pk,
            tz=get_current_timezone(),
            track_pk=filter_track_pk,
            space_page=room_page,
            date_selection=date_selection,
        )

        context: dict[str, object] = {
            "grid": grid,
            "filter_track_pk": filter_track_pk,
            "date_selection": grid.date_selection,
            "slug": slug,
        }
        return TemplateResponse(
            self.request, "panel/parts/timetable-grid.html", context
        )


class TimetableAssignView(PanelAccessMixin, EventContextMixin, View):
    """POST: assign a session to a space and time."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            session_pk = int(self.request.POST["session_pk"])
            placement = SessionPlacement(
                space_pk=int(self.request.POST["space_pk"]),
                start_time=datetime.fromisoformat(self.request.POST["start_time"]),
                end_time=datetime.fromisoformat(self.request.POST["end_time"]),
            )
        except KeyError, ValueError:
            return HttpResponse(status=422)

        uow = self.request.di.uow
        try:
            TimetableService(uow).assign_session(
                session_pk=session_pk,
                placement=placement,
                event_pk=current_event.pk,
                user_pk=self.request.user.pk,
            )
        except ValueError, NotFoundError:
            return HttpResponse(status=422)

        self.request.services.waitlist_promotion.fill_freed_seats(session_id=session_pk)

        try:
            conflicts = ConflictDetectionService(uow).detect_for_assignment(
                event_pk=current_event.pk, session_pk=session_pk
            )
        except NotFoundError:
            # A concurrent unassign can remove the placement between the
            # committed write and this advisory sweep; that is not a failure
            # of the assignment, so report no conflicts.
            conflicts = []

        trigger_data: dict[str, object] = {"timetableChanged": {}}
        if conflicts:
            trigger_data["timetableConflicts"] = {
                "conflicts": [c.model_dump(mode="json") for c in conflicts]
            }
        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps(trigger_data)
        return response


class TimetableUnassignView(PanelAccessMixin, EventContextMixin, View):
    """POST: remove a session from the timetable."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            session_pk = int(self.request.POST["session_pk"])
        except KeyError, ValueError:
            return HttpResponse(status=422)

        uow = self.request.di.uow
        try:
            TimetableService(uow).unassign_session(
                session_pk=session_pk,
                event_pk=current_event.pk,
                user_pk=self.request.user.pk,
            )
        except NotFoundError:
            return HttpResponse(status=422)

        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({"timetableChanged": {}})
        return response


class TimetableConfirmView(PanelAccessMixin, EventContextMixin, View):
    """POST: set confirmation on one scheduled program item."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            agenda_item_pk = int(self.request.POST["agenda_item_pk"])
        except KeyError, ValueError:
            return HttpResponse(status=422)
        confirmed_raw = self.request.POST.get("confirmed")
        if confirmed_raw not in {"true", "false"}:
            return HttpResponse(status=422)

        try:
            self.request.services.session_confirmation.set_session_confirmed(
                event_pk=current_event.pk,
                agenda_item_pk=agenda_item_pk,
                confirmed=confirmed_raw == "true",
            )
        except NotFoundError:
            return HttpResponse(status=422)

        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({"timetableChanged": {}})
        return response


class TimetableOverviewPageView(PanelAccessMixin, EventContextMixin, View):
    """Full page: sphere-manager overview — heatmap and track progress."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "timetable"

        uow = self.request.di.uow
        overview = TimetableOverviewService(uow)

        context["heatmap"] = overview.build_heatmap(
            current_event.pk, tz=get_current_timezone()
        )
        context["track_progress"] = overview.track_progress(current_event.pk)
        context["capacity_hours"] = overview.capacity_hours(current_event.pk)
        context["slug"] = slug
        context["tab_urls"] = timetable_tab_urls(slug)
        context["active_tab"] = "overview"
        return TemplateResponse(self.request, "panel/timetable-overview.html", context)


class TimetableProblemsPageView(PanelAccessMixin, EventContextMixin, View):
    """Full page: consolidated triage of conflicts and preferred-slot violations."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "timetable"

        uow = self.request.di.uow
        conflict_service = ConflictDetectionService(uow)
        overview = TimetableOverviewService(uow)
        all_conflicts = overview.get_all_conflicts(current_event.pk)
        slot_violations = conflict_service.list_preferred_slot_violations(
            event_pk=current_event.pk, track_pk=None
        )

        context["conflicts_grouped"] = overview.all_conflicts_grouped(
            current_event.pk, conflicts=all_conflicts
        )
        context["slot_violations"] = slot_violations
        context["slug"] = slug
        context["tab_urls"] = timetable_tab_urls(slug)
        context["active_tab"] = "problems"
        return TemplateResponse(self.request, "panel/timetable-problems.html", context)


class TimetableLogPageView(PanelAccessMixin, EventContextMixin, View):
    """Full page: timetable assignment activity log with filters."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "timetable"

        uow = self.request.di.uow

        space_pk_raw = self.request.GET.get("space", "").strip()
        space_pk = int(space_pk_raw) if space_pk_raw.isdigit() else None

        logs = uow.schedule_change_logs.list_by_event(
            current_event.pk, space_pk=space_pk
        )
        spaces = uow.spaces.list_by_event(current_event.pk)

        context["logs"] = logs
        context["revertible_pks"] = set(
            uow.schedule_change_logs.latest_pks_by_session(current_event.pk).values()
        )
        context["spaces"] = spaces
        context["space_pk"] = space_pk
        context["slug"] = slug
        context["tab_urls"] = timetable_tab_urls(slug)
        context["active_tab"] = "log"
        return TemplateResponse(self.request, "panel/timetable-log.html", context)


class TimetableRevertView(PanelAccessMixin, EventContextMixin, View):
    """POST: revert a logged timetable change."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            log_pk = int(self.request.POST["log_pk"])
        except KeyError, ValueError:
            return HttpResponse(status=422)

        uow = self.request.di.uow
        try:
            TimetableService(uow).revert_change(
                log_pk=log_pk, event_pk=current_event.pk, user_pk=self.request.user.pk
            )
        except ValueError, NotFoundError:
            return HttpResponse(status=422)

        return redirect("panel:timetable-log", slug=slug)


class TimetableConflictsPartView(PanelAccessMixin, EventContextMixin, View):
    """HTMX partial: permanent conflict panel."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        _, _, filter_track_pk = self.get_track_filter_context(current_event.pk)

        conflicts = ConflictDetectionService(self.request.di.uow).list_all_for_track(
            event_pk=current_event.pk, track_pk=filter_track_pk
        )

        context = {
            "conflicts": conflicts,
            "slug": slug,
            "filter_track_pk": filter_track_pk,
        }
        return TemplateResponse(
            self.request, "panel/parts/timetable-conflict-panel.html", context
        )
