from datetime import datetime, time, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import get_current_timezone

from ludamus.links.db.django.models import TimeSlot
from ludamus.pacts import EventDTO, TimeSlotDTO
from tests.integration.conftest import EventFactory, TimeSlotFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTimeSlotEditPageView:
    """Tests for /panel/event/<slug>/cfp/time-slots/<pk>/edit/ page."""

    @staticmethod
    def get_url(event, time_slot):
        return reverse(
            "panel:time-slot-edit", kwargs={"slug": event.slug, "pk": time_slot.pk}
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event, time_slot):
        url = self.get_url(event, time_slot)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(
        self, authenticated_client, event, time_slot
    ):
        response = authenticated_client.get(self.get_url(event, time_slot))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event, time_slot))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slot-edit.html",
            context_data={
                "active_nav": "cfp",
                "form": ANY,
                "time_slot": TimeSlotDTO.model_validate(time_slot),
                "events": [EventDTO.model_validate(event)],
                "current_event": EventDTO.model_validate(event),
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
            },
        )

    def test_post_updates_time_slot(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)
        date_str = event.start_time.date().isoformat()

        response = authenticated_client.post(
            self.get_url(event, time_slot),
            {
                "date": date_str,
                "end_date": date_str,
                "start_time": "14:00",
                "end_time": "16:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Time slot updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        time_slot.refresh_from_db()
        tz = get_current_timezone()
        expected_date = event.start_time.date()
        assert time_slot.start_time == datetime.combine(
            expected_date, time(14, 0), tzinfo=tz
        )
        assert time_slot.end_time == datetime.combine(
            expected_date, time(16, 0), tzinfo=tz
        )

    def test_post_updates_midnight_crossing_slot(
        self, authenticated_client, active_user, sphere
    ):
        """Edit a slot to cross midnight; end_date auto-advances."""
        sphere.managers.add(active_user)
        tz = get_current_timezone()
        start = datetime.combine(
            (datetime.now(tz) + timedelta(days=7)).date(), time(20, 0), tzinfo=tz
        )
        event = EventFactory(
            sphere=sphere, start_time=start, end_time=start + timedelta(hours=8)
        )
        slot = TimeSlotFactory(
            event=event,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=2),
        )
        date_str = event.start_time.date().isoformat()

        response = authenticated_client.post(
            self.get_url(event, slot),
            {
                "date": date_str,
                "end_date": date_str,
                "start_time": "22:00",
                "end_time": "02:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Time slot updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        slot.refresh_from_db()
        expected_date = event.start_time.date()
        assert slot.start_time == datetime.combine(
            expected_date, time(22, 0), tzinfo=tz
        )
        assert slot.end_time == datetime.combine(
            expected_date + timedelta(days=1), time(2, 0), tzinfo=tz
        )

    def test_post_invalid_form_returns_errors(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event, time_slot),
            {"date": "", "start_time": "", "end_time": ""},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slot-edit.html",
            context_data={
                "active_nav": "cfp",
                "form": ANY,
                "time_slot": TimeSlotDTO.model_validate(time_slot),
                "events": [EventDTO.model_validate(event)],
                "current_event": EventDTO.model_validate(event),
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
            },
        )
        assert response.context["form"].errors

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:time-slot-edit", kwargs={"slug": "nonexistent", "pk": 99999}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:time-slot-edit", kwargs={"slug": "nonexistent", "pk": 99999}
        )

        response = authenticated_client.post(
            url, {"date": "2026-03-10", "start_time": "10:00", "end_time": "12:00"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_redirects_on_invalid_pk(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:time-slot-edit", kwargs={"slug": event.slug, "pk": 99999})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Time slot not found.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )

    def test_post_redirects_on_invalid_pk(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:time-slot-edit", kwargs={"slug": event.slug, "pk": 99999})

        response = authenticated_client.post(
            url, {"date": "2026-03-10", "start_time": "10:00", "end_time": "12:00"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Time slot not found.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )

    def test_post_rejects_slot_outside_event_dates(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)
        before_event = (event.start_time - timedelta(days=5)).date().isoformat()

        response = authenticated_client.post(
            self.get_url(event, time_slot),
            {
                "date": before_event,
                "end_date": before_event,
                "start_time": "10:00",
                "end_time": "12:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slot-edit.html",
            context_data={
                "active_nav": "cfp",
                "form": ANY,
                "time_slot": TimeSlotDTO.model_validate(time_slot),
                "events": [EventDTO.model_validate(event)],
                "current_event": EventDTO.model_validate(event),
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
            },
        )
        assert (
            "Time slot must be within event dates."
            in response.context["form"].non_field_errors()
        )

    def test_post_rejects_overlapping_slot(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)
        tz = get_current_timezone()
        slot_start = datetime.combine(event.start_time.date(), time(10, 0), tzinfo=tz)
        other = TimeSlot.objects.create(
            event=event, start_time=slot_start, end_time=slot_start + timedelta(hours=2)
        )
        date_str = event.start_time.date().isoformat()

        response = authenticated_client.post(
            self.get_url(event, time_slot),
            {
                "date": date_str,
                "end_date": date_str,
                "start_time": "10:30",
                "end_time": "11:30",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slot-edit.html",
            context_data={
                "active_nav": "cfp",
                "form": ANY,
                "time_slot": TimeSlotDTO.model_validate(time_slot),
                "events": [EventDTO.model_validate(event)],
                "current_event": EventDTO.model_validate(event),
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
            },
        )
        assert (
            "Time slot overlaps with an existing slot."
            in response.context["form"].non_field_errors()
        )
        other.delete()

    def test_post_allows_updating_same_slot_without_overlap_error(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)
        date_str = event.start_time.date().isoformat()

        response = authenticated_client.post(
            self.get_url(event, time_slot),
            {
                "date": date_str,
                "end_date": date_str,
                "start_time": "10:00",
                "end_time": "12:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Time slot updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )

    def test_post_rejects_multi_day_slot_outside_event(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)
        start_date = event.start_time.date().isoformat()
        end_date = (event.end_time + timedelta(days=5)).date().isoformat()

        response = authenticated_client.post(
            self.get_url(event, time_slot),
            {
                "date": start_date,
                "end_date": end_date,
                "start_time": "22:00",
                "end_time": "02:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slot-edit.html",
            context_data={
                "active_nav": "cfp",
                "form": ANY,
                "time_slot": TimeSlotDTO.model_validate(time_slot),
                "events": [EventDTO.model_validate(event)],
                "current_event": EventDTO.model_validate(event),
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
            },
        )
        assert (
            "Time slot must be within event dates."
            in response.context["form"].non_field_errors()
        )

    def test_get_rejects_slot_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        other_slot = TimeSlotFactory(event=other_event)
        url = reverse(
            "panel:time-slot-edit", kwargs={"slug": event.slug, "pk": other_slot.pk}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Time slot not found.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
