from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.links.db.django.models import TimeSlot
from ludamus.pacts import EventDTO, TimeSlotDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTimeSlotsPageView:
    """Tests for /panel/event/<slug>/cfp/time-slots/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:time-slots", kwargs={"slug": event.slug})

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
        # Pin event to a single local day so day count is predictable.
        local_start = localtime(event.start_time).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        event.start_time = local_start
        event.end_time = local_start.replace(hour=18)
        event.save()

        response = authenticated_client.get(self.get_url(event))

        day = local_start.date()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slots.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "cfp",
                "active_tab": "time_slots",
                "tab_urls": {
                    "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
                    "host": reverse(
                        "panel:personal-data-fields", kwargs={"slug": event.slug}
                    ),
                    "session": reverse(
                        "panel:session-fields", kwargs={"slug": event.slug}
                    ),
                    "time_slots": reverse(
                        "panel:time-slots", kwargs={"slug": event.slug}
                    ),
                },
                "time_slots": [],
                "days": {day.isoformat(): []},
                "orphaned_slots": [],
                "continuation_slots": set(),
                "event_days": [day],
                "page": 0,
                "has_prev": False,
                "has_next": False,
                "total_pages": 1,
                "create_form": ANY,
                "dated_create_forms": [
                    {
                        "day": day,
                        "modal_id": f"time-slot-create-modal-{day:%Y%m%d}",
                        "form": ANY,
                    }
                ],
            },
            contains=[
                'aria-controls="time-slot-create-modal"',
                f'aria-controls="time-slot-create-modal-{day:%Y%m%d}"',
                '<dialog id="time-slot-create-modal"',
                "New Time Slot",
            ],
        )

    def test_get_returns_empty_state_when_no_slots(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert response.context["time_slots"] == []

    def test_get_returns_time_slots_grouped_by_date(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        day1 = localtime(event.start_time).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        TimeSlot.objects.create(
            event=event,
            start_time=day1 + timedelta(hours=3),
            end_time=day1 + timedelta(hours=5),
        )

        response = authenticated_client.get(self.get_url(event))

        assert len(response.context["time_slots"]) == 1 + 1
        days = response.context["days"]
        date_key = day1.date().isoformat()
        assert len(days[date_key]) == 1 + 1

    def test_get_groups_slots_across_multiple_days(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.end_time = event.start_time + timedelta(days=2)
        event.save()
        day1 = localtime(event.start_time).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        day2 = day1 + timedelta(days=1)
        TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        TimeSlot.objects.create(
            event=event, start_time=day2, end_time=day2 + timedelta(hours=2)
        )

        response = authenticated_client.get(self.get_url(event))

        days = response.context["days"]
        assert day1.date().isoformat() in days
        assert day2.date().isoformat() in days

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:time-slots", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_returns_event_days_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.end_time = event.start_time + timedelta(days=2)
        event.save()

        response = authenticated_client.get(self.get_url(event))

        event_days = response.context["event_days"]
        local_start = localtime(event.start_time).date()
        assert len(event_days) == 1 + 2
        assert event_days[0] == local_start
        assert event_days[1] == local_start + timedelta(days=1)
        assert event_days[2] == local_start + timedelta(days=2)

    def test_get_paginates_when_more_than_3_days(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.end_time = event.start_time + timedelta(days=4)
        event.save()

        response = authenticated_client.get(self.get_url(event))

        start = localtime(event.start_time).date()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slots.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "cfp",
                "active_tab": "time_slots",
                "tab_urls": {
                    "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
                    "host": reverse(
                        "panel:personal-data-fields", kwargs={"slug": event.slug}
                    ),
                    "session": reverse(
                        "panel:session-fields", kwargs={"slug": event.slug}
                    ),
                    "time_slots": reverse(
                        "panel:time-slots", kwargs={"slug": event.slug}
                    ),
                },
                "time_slots": [],
                "days": {(start + timedelta(days=i)).isoformat(): [] for i in range(3)},
                "orphaned_slots": [],
                "continuation_slots": set(),
                "event_days": [start + timedelta(days=i) for i in range(3)],
                "page": 0,
                "has_prev": False,
                "has_next": True,
                "total_pages": 1 + 1,
                "create_form": ANY,
                "dated_create_forms": [
                    {
                        "day": start + timedelta(days=i),
                        "modal_id": (
                            "time-slot-create-modal-"
                            f"{start + timedelta(days=i):%Y%m%d}"
                        ),
                        "form": ANY,
                    }
                    for i in range(3)
                ],
            },
        )

    def test_get_second_page_shows_remaining_days(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.end_time = event.start_time + timedelta(days=4)
        event.save()

        response = authenticated_client.get(self.get_url(event) + "?page=1")

        start = localtime(event.start_time).date()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/time-slots.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "cfp",
                "active_tab": "time_slots",
                "tab_urls": {
                    "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
                    "host": reverse(
                        "panel:personal-data-fields", kwargs={"slug": event.slug}
                    ),
                    "session": reverse(
                        "panel:session-fields", kwargs={"slug": event.slug}
                    ),
                    "time_slots": reverse(
                        "panel:time-slots", kwargs={"slug": event.slug}
                    ),
                },
                "time_slots": [],
                "days": {
                    (start + timedelta(days=i)).isoformat(): [] for i in range(3, 5)
                },
                "orphaned_slots": [],
                "continuation_slots": set(),
                "event_days": [start + timedelta(days=i) for i in range(3, 5)],
                "page": 1,
                "has_prev": True,
                "has_next": False,
                "total_pages": 1 + 1,
                "create_form": ANY,
                "dated_create_forms": [
                    {
                        "day": start + timedelta(days=i),
                        "modal_id": (
                            "time-slot-create-modal-"
                            f"{start + timedelta(days=i):%Y%m%d}"
                        ),
                        "form": ANY,
                    }
                    for i in range(3, 5)
                ],
            },
        )

    def test_get_shows_orphaned_slots_before_event_start(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        before_event = event.start_time - timedelta(days=1)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=before_event.replace(hour=10, minute=0, second=0, microsecond=0),
            end_time=before_event.replace(hour=12, minute=0, second=0, microsecond=0),
        )

        response = authenticated_client.get(self.get_url(event))

        orphaned = response.context["orphaned_slots"]
        assert len(orphaned) == 1
        assert orphaned[0] == TimeSlotDTO.model_validate(slot)
        day_key = localtime(event.start_time).date().isoformat()
        assert all(s.pk != slot.pk for s in response.context["days"][day_key])

    def test_get_shows_orphaned_slots_after_event_end(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        # Pin event to a single local day so "after event" is unambiguous.
        local_start = localtime(event.start_time).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        event.start_time = local_start
        event.end_time = local_start.replace(hour=18)
        event.save()
        after_local = local_start + timedelta(days=2)
        slot = TimeSlot.objects.create(
            event=event,
            start_time=after_local.replace(hour=10),
            end_time=after_local.replace(hour=12),
        )

        response = authenticated_client.get(self.get_url(event))

        orphaned = response.context["orphaned_slots"]
        assert len(orphaned) == 1
        assert orphaned[0] == TimeSlotDTO.model_validate(slot)
        for slots in response.context["days"].values():
            assert all(s.pk != slot.pk for s in slots)

    def test_get_multi_day_slot_appears_in_both_day_columns(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.end_time = event.start_time + timedelta(days=2)
        event.save()
        # Build times that span midnight in local time (Europe/Warsaw).
        local_start = localtime(event.start_time)
        day1_start = local_start.replace(hour=22, minute=0, second=0, microsecond=0)
        day2_end = (day1_start + timedelta(days=1)).replace(hour=2, minute=0)
        slot = TimeSlot.objects.create(
            event=event, start_time=day1_start, end_time=day2_end
        )

        response = authenticated_client.get(self.get_url(event))

        days = response.context["days"]
        day1_key = day1_start.date().isoformat()
        day2_key = day2_end.date().isoformat()
        slot_dto = TimeSlotDTO.model_validate(slot)
        assert slot_dto in days[day1_key]
        assert slot_dto in days[day2_key]
        continuation = response.context["continuation_slots"]
        assert (slot.pk, day2_key) in continuation
        assert (slot.pk, day1_key) not in continuation
