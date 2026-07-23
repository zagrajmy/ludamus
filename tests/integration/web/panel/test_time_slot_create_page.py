from datetime import datetime, time, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import get_current_timezone

from ludamus.links.db.django.models import TimeSlot
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _create_modal_form(response):
    assert_response(
        response, HTTPStatus.OK, template_name="panel/time-slots.html", context_data=ANY
    )
    return response.context["create_form"]


class TestTimeSlotCreatePageView:
    """Tests for /panel/event/<slug>/cfp/time-slots/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:time-slot-create", kwargs={"slug": event.slug})

    @staticmethod
    def _event_date_str(event):
        return event.start_time.date().isoformat()

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=(
                reverse("panel:time-slots", kwargs={"slug": event.slug}) + "?create=1"
            ),
        )

    def test_get_prefills_date_from_query_param(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.get_url(event) + "?date=2026-03-10", follow=True
        )

        assert response.redirect_chain == [
            (
                reverse("panel:time-slots", kwargs={"slug": event.slug})
                + "?create=1&date=2026-03-10",
                HTTPStatus.FOUND,
            )
        ]
        assert response.context["create_form"].initial["date"] == "2026-03-10"

    def test_get_ignores_invalid_date_query_param(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.get_url(event) + "?date=not-a-date", follow=True
        )

        assert response.status_code == HTTPStatus.OK
        assert response.redirect_chain == [
            (
                reverse("panel:time-slots", kwargs={"slug": event.slug}) + "?create=1",
                HTTPStatus.FOUND,
            )
        ]
        assert "date" not in response.context["create_form"].initial

    def test_post_creates_time_slot(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        date_str = self._event_date_str(event)

        response = authenticated_client.post(
            self.get_url(event),
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
            messages=[(messages.SUCCESS, "Time slot created successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        assert TimeSlot.objects.filter(event=event).count() == 1
        slot = TimeSlot.objects.get(event=event)
        tz = get_current_timezone()
        expected_date = event.start_time.date()
        assert slot.start_time == datetime.combine(
            expected_date, time(10, 0), tzinfo=tz
        )
        assert slot.end_time == datetime.combine(expected_date, time(12, 0), tzinfo=tz)

    def test_post_creates_midnight_crossing_slot(
        self, authenticated_client, active_user, sphere
    ):
        """Slot 22:00-02:00 with same date auto-advances end to next day."""
        sphere.managers.add(active_user)
        tz = get_current_timezone()
        start = datetime.combine(
            (datetime.now(tz) + timedelta(days=7)).date(), time(20, 0), tzinfo=tz
        )
        event = EventFactory(
            sphere=sphere, start_time=start, end_time=start + timedelta(hours=8)
        )
        date_str = event.start_time.date().isoformat()

        response = authenticated_client.post(
            self.get_url(event),
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
            messages=[(messages.SUCCESS, "Time slot created successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        slot = TimeSlot.objects.get(event=event)
        expected_date = event.start_time.date()
        assert slot.start_time == datetime.combine(
            expected_date, time(22, 0), tzinfo=tz
        )
        assert slot.end_time == datetime.combine(
            expected_date + timedelta(days=1), time(2, 0), tzinfo=tz
        )

    def test_post_invalid_form_returns_errors(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), {"date": "", "start_time": "", "end_time": ""}
        )

        assert _create_modal_form(response).errors

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:time-slot-create", kwargs={"slug": "nonexistent"})

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
        url = reverse("panel:time-slot-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(
            url, {"date": "2026-03-10", "start_time": "10:00", "end_time": "12:00"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_rejects_slot_when_start_equals_end(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        date_str = self._event_date_str(event)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "date": date_str,
                "end_date": date_str,
                "start_time": "10:00",
                "end_time": "10:00",
            },
        )

        form = _create_modal_form(response)
        assert "Start must be before end." in form.non_field_errors()
        assert TimeSlot.objects.filter(event=event).count() == 0

    def test_post_rejects_slot_outside_event_dates(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        before_event = (event.start_time - timedelta(days=5)).date().isoformat()

        response = authenticated_client.post(
            self.get_url(event),
            {
                "date": before_event,
                "end_date": before_event,
                "start_time": "10:00",
                "end_time": "12:00",
            },
        )

        form = _create_modal_form(response)
        assert "Time slot must be within event dates." in form.non_field_errors()
        assert TimeSlot.objects.filter(event=event).count() == 0

    def test_post_rejects_slot_after_event_end(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        after_event = (event.end_time + timedelta(days=5)).date().isoformat()

        response = authenticated_client.post(
            self.get_url(event),
            {
                "date": after_event,
                "end_date": after_event,
                "start_time": "10:00",
                "end_time": "12:00",
            },
        )

        form = _create_modal_form(response)
        assert "Time slot must be within event dates." in form.non_field_errors()
        assert TimeSlot.objects.filter(event=event).count() == 0

    def test_post_rejects_overlapping_slot(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        date_str = self._event_date_str(event)
        tz = get_current_timezone()
        slot_start = datetime.combine(event.start_time.date(), time(10, 0), tzinfo=tz)
        TimeSlot.objects.create(
            event=event, start_time=slot_start, end_time=slot_start + timedelta(hours=2)
        )

        response = authenticated_client.post(
            self.get_url(event),
            {
                "date": date_str,
                "end_date": date_str,
                "start_time": "11:00",
                "end_time": "13:00",
            },
        )

        form = _create_modal_form(response)
        assert "Time slot overlaps with an existing slot." in form.non_field_errors()
        assert TimeSlot.objects.filter(event=event).count() == 1

    def test_post_allows_adjacent_slots(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        date_str = self._event_date_str(event)
        tz = get_current_timezone()
        slot_start = datetime.combine(event.start_time.date(), time(10, 0), tzinfo=tz)
        TimeSlot.objects.create(
            event=event, start_time=slot_start, end_time=slot_start + timedelta(hours=2)
        )

        response = authenticated_client.post(
            self.get_url(event),
            {
                "date": date_str,
                "end_date": date_str,
                "start_time": "12:00",
                "end_time": "14:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Time slot created successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        assert TimeSlot.objects.filter(event=event).count() == 1 + 1

    def test_post_creates_multi_day_slot(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.end_time = event.start_time + timedelta(days=2)
        event.save()
        start_date = event.start_time.date().isoformat()
        end_date = (event.start_time + timedelta(days=1)).date().isoformat()

        response = authenticated_client.post(
            self.get_url(event),
            {
                "date": start_date,
                "end_date": end_date,
                "start_time": "22:00",
                "end_time": "02:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Time slot created successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        slot = TimeSlot.objects.get(event=event)
        assert slot.start_time.date() == event.start_time.date()
        assert slot.end_time.date() == (event.start_time + timedelta(days=1)).date()

    def test_post_rejects_multi_day_slot_outside_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        start_date = event.start_time.date().isoformat()
        end_date = (event.end_time + timedelta(days=5)).date().isoformat()

        response = authenticated_client.post(
            self.get_url(event),
            {
                "date": start_date,
                "end_date": end_date,
                "start_time": "22:00",
                "end_time": "02:00",
            },
        )

        form = _create_modal_form(response)
        assert "Time slot must be within event dates." in form.non_field_errors()
        assert TimeSlot.objects.filter(event=event).count() == 0
