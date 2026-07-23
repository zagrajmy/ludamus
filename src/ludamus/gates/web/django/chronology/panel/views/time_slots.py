# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""Time slot views for the CFP."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.timezone import get_current_timezone, localtime
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    cfp_tab_urls,
)
from ludamus.gates.web.django.forms import TimeSlotForm
from ludamus.mills import PanelService
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO, TimeSlotDTO


def _validate_time_slot(
    form: TimeSlotForm,
    start: datetime,
    end: datetime,
    event: EventDTO,
    existing: list[TimeSlotDTO],
) -> bool:
    errors = PanelService.validate_time_slot(start, end, event, existing)
    for error in errors:
        form.add_error(None, _(error))
    return not errors


def _date_initial(raw_date: str | None) -> dict[str, str]:
    if raw_date is None:
        return {}
    try:
        date.fromisoformat(raw_date)
    except ValueError:
        return {}
    return {"date": raw_date, "end_date": raw_date}


def _event_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _time_slots_context(
    request: PanelRequest, event: EventDTO, *, create_form: TimeSlotForm | None = None
) -> dict[str, object]:
    days_per_page = TimeSlotsPageView.DAYS_PER_PAGE
    all_days = _event_days(
        localtime(event.start_time).date(), localtime(event.end_time).date()
    )
    page = int(request.GET.get("page", 0))
    total_pages = max(1, (len(all_days) + days_per_page - 1) // days_per_page)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * days_per_page
    visible_days = all_days[start_idx : start_idx + days_per_page]

    time_slots = request.di.uow.time_slots.list_by_event(event.pk)

    event_start = localtime(event.start_time).date()
    event_end = localtime(event.end_time).date()
    visible_set = set(visible_days)
    days: dict[str, list[TimeSlotDTO]] = {day.isoformat(): [] for day in visible_days}
    orphaned_slots: list[TimeSlotDTO] = []
    continuation_slots: set[tuple[int, str]] = set()
    for time_slot in time_slots:
        slot_date = localtime(time_slot.start_time).date()
        end_date = localtime(time_slot.end_time).date()
        if slot_date in visible_set:
            days[slot_date.isoformat()].append(time_slot)
        elif slot_date < event_start or slot_date > event_end:
            orphaned_slots.append(time_slot)
        if end_date != slot_date and end_date in visible_set:
            days[end_date.isoformat()].append(time_slot)
            continuation_slots.add((time_slot.pk, end_date.isoformat()))

    return {
        "active_nav": "cfp",
        "active_tab": "time_slots",
        "tab_urls": cfp_tab_urls(event.slug),
        "time_slots": time_slots,
        "days": days,
        "orphaned_slots": orphaned_slots,
        "continuation_slots": continuation_slots,
        "event_days": visible_days,
        "page": page,
        "has_prev": page > 0,
        "has_next": page < total_pages - 1,
        "total_pages": total_pages,
        "create_form": (
            create_form
            if create_form is not None
            else TimeSlotForm(
                initial=_date_initial(request.GET.get("date")),
                auto_id="new_time_slot_%s",
            )
        ),
        "dated_create_forms": [
            {
                "day": day,
                "modal_id": f"time-slot-create-modal-{day:%Y%m%d}",
                "form": TimeSlotForm(
                    initial={"date": day.isoformat(), "end_date": day.isoformat()},
                    auto_id=f"new_time_slot_{day:%Y%m%d}_%s",
                ),
            }
            for day in visible_days
        ],
    }


class TimeSlotsPageView(PanelAccessMixin, EventContextMixin, View):
    """List time slots for an event, grouped by date."""

    DAYS_PER_PAGE = 3
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context.update(_time_slots_context(self.request, current_event))
        return TemplateResponse(self.request, "panel/time-slots.html", context)


class TimeSlotCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new time slot for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        time_slots_url = reverse("panel:time-slots", kwargs={"slug": slug})
        date_param = self.request.GET.get("date")
        if _date_initial(date_param):
            return redirect(f"{time_slots_url}?create=1&date={date_param}")
        return redirect(f"{time_slots_url}?create=1")

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = TimeSlotForm(self.request.POST)
        if not form.is_valid():
            context.update(
                _time_slots_context(self.request, current_event, create_form=form)
            )
            return TemplateResponse(self.request, "panel/time-slots.html", context)

        start_date = form.cleaned_data["date"]
        end_date = form.cleaned_data["end_date"]
        tz = get_current_timezone()
        start_time = datetime.combine(
            start_date, form.cleaned_data["start_time"], tzinfo=tz
        )
        end_time = datetime.combine(end_date, form.cleaned_data["end_time"], tzinfo=tz)
        if end_time < start_time and end_date == start_date:
            end_time += timedelta(days=1)

        existing = self.request.di.uow.time_slots.list_by_event(current_event.pk)
        if not _validate_time_slot(form, start_time, end_time, current_event, existing):
            context.update(
                _time_slots_context(self.request, current_event, create_form=form)
            )
            return TemplateResponse(self.request, "panel/time-slots.html", context)

        self.request.di.uow.time_slots.create(current_event.pk, start_time, end_time)

        messages.success(self.request, _("Time slot created successfully."))
        return redirect("panel:time-slots", slug=slug)


class TimeSlotEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing time slot."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            time_slot = self.request.di.uow.time_slots.read_by_event(
                current_event.pk, pk
            )
        except NotFoundError:
            messages.error(self.request, _("Time slot not found."))
            return redirect("panel:time-slots", slug=slug)

        local_start = localtime(time_slot.start_time)
        local_end = localtime(time_slot.end_time)
        initial: dict[str, str] = {
            "date": local_start.date().isoformat(),
            "end_date": local_end.date().isoformat(),
            "start_time": local_start.strftime("%H:%M"),
            "end_time": local_end.strftime("%H:%M"),
        }

        context["active_nav"] = "cfp"
        context["time_slot"] = time_slot
        context["form"] = TimeSlotForm(initial=initial)
        return TemplateResponse(self.request, "panel/time-slot-edit.html", context)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            time_slot = self.request.di.uow.time_slots.read_by_event(
                current_event.pk, pk
            )
        except NotFoundError:
            messages.error(self.request, _("Time slot not found."))
            return redirect("panel:time-slots", slug=slug)

        form = TimeSlotForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "cfp"
            context["time_slot"] = time_slot
            context["form"] = form
            return TemplateResponse(self.request, "panel/time-slot-edit.html", context)

        start_date = form.cleaned_data["date"]
        end_date = form.cleaned_data["end_date"]
        tz = get_current_timezone()
        start_time = datetime.combine(
            start_date, form.cleaned_data["start_time"], tzinfo=tz
        )
        end_time = datetime.combine(end_date, form.cleaned_data["end_time"], tzinfo=tz)
        if end_time < start_time and end_date == start_date:
            end_time += timedelta(days=1)

        existing = [
            ts
            for ts in self.request.di.uow.time_slots.list_by_event(current_event.pk)
            if ts.pk != pk
        ]
        if not _validate_time_slot(form, start_time, end_time, current_event, existing):
            context["active_nav"] = "cfp"
            context["time_slot"] = time_slot
            context["form"] = form
            return TemplateResponse(self.request, "panel/time-slot-edit.html", context)

        self.request.di.uow.time_slots.update(pk, start_time, end_time)

        messages.success(self.request, _("Time slot updated successfully."))
        return redirect("panel:time-slots", slug=slug)


class TimeSlotDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    """Delete a time slot (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            self.request.di.uow.time_slots.read_by_event(current_event.pk, pk)
        except NotFoundError:
            messages.error(self.request, _("Time slot not found."))
            return redirect("panel:time-slots", slug=slug)

        service = PanelService(self.request.di.uow)
        if not service.delete_time_slot(pk):
            messages.error(
                self.request, _("Cannot delete time slot used in proposals.")
            )
            return redirect("panel:time-slots", slug=slug)

        messages.success(self.request, _("Time slot deleted successfully."))
        return redirect("panel:time-slots", slug=slug)
