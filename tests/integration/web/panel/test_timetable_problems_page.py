from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import (
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    PreferredSlotRangeDTO,
    PreferredSlotViolationDTO,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
ONE_SCHEDULED_SESSION_STATS = {
    "hosts_count": 1,
    "pending_proposals": 1,
    "rooms_count": 1,
    "scheduled_sessions": 1,
    "total_proposals": 1,
    "total_sessions": 2,
}


class TestTimetableProblemsPageView:
    """Tests for /panel/event/<slug>/schedule/problems/ problems page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-problems", kwargs={"slug": event.slug})

    @staticmethod
    def expected_context(event, *, stats, conflicts_grouped, slot_violations):
        return {
            "current_event": EventDTO.model_validate(event),
            "events": [EventDTO.model_validate(event)],
            "is_proposal_active": False,
            "stats": stats,
            "active_nav": "timetable",
            "conflicts_grouped": conflicts_grouped,
            "slot_violations": slot_violations,
            "slug": event.slug,
            "tab_urls": {
                "timetable": reverse("panel:timetable", kwargs={"slug": event.slug}),
                "log": reverse("panel:timetable-log", kwargs={"slug": event.slug}),
                "overview": reverse(
                    "panel:timetable-overview", kwargs={"slug": event.slug}
                ),
                "problems": reverse(
                    "panel:timetable-problems", kwargs={"slug": event.slug}
                ),
            },
            "active_tab": "problems",
        }

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-problems", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_returns_problems_template(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats={
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                conflicts_grouped={},
                slot_violations=[],
            ),
        )

    def test_lists_space_overlap_conflict(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session_a = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        session_b = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(
            session=session_a, space=space, start_time=start, end_time=end
        )
        AgendaItemFactory(
            session=session_b, space=space, start_time=start, end_time=end
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats={
                    "hosts_count": 2,
                    "pending_proposals": 2,
                    "rooms_count": 1,
                    "scheduled_sessions": 2,
                    "total_proposals": 2,
                    "total_sessions": 4,
                },
                conflicts_grouped={
                    ConflictType.SPACE_OVERLAP: [
                        ConflictDTO(
                            type=ConflictType.SPACE_OVERLAP,
                            severity=ConflictSeverity.ERROR,
                            subject_session_title=session_a.title,
                            subject_session_pk=session_a.pk,
                            session_title=session_b.title,
                            session_pk=session_b.pk,
                        )
                    ]
                },
                slot_violations=[],
            ),
        )

    def test_lists_session_outside_preferred_slot(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        preferred_slot = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=4),
            end_time=event.start_time + timedelta(hours=6),
        )
        session.time_slots.add(preferred_slot)
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                slot_violations=[
                    PreferredSlotViolationDTO(
                        session_pk=session.pk,
                        session_title=session.title,
                        scheduled_start=start,
                        scheduled_end=end,
                        preferred_slots=[
                            PreferredSlotRangeDTO(
                                start_time=preferred_slot.start_time,
                                end_time=preferred_slot.end_time,
                            )
                        ],
                        track_name=None,
                        manager_names=[],
                    )
                ],
            ),
        )

    def test_skips_session_inside_preferred_slot(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        preferred_slot = TimeSlotFactory(
            event=event,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=2),
        )
        session.time_slots.add(preferred_slot)
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                slot_violations=[],
            ),
        )

    def test_skips_session_spanning_contiguous_preferred_slots(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        session.time_slots.add(
            TimeSlotFactory(
                event=event,
                start_time=event.start_time,
                end_time=event.start_time + timedelta(hours=4),
            ),
            TimeSlotFactory(
                event=event,
                start_time=event.start_time + timedelta(hours=4),
                end_time=event.start_time + timedelta(hours=8),
            ),
        )
        start = event.start_time + timedelta(hours=2)
        end = event.start_time + timedelta(hours=6)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                slot_violations=[],
            ),
        )

    def test_lists_session_spanning_gap_between_preferred_slots(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        early_slot = TimeSlotFactory(
            event=event,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=2),
        )
        late_slot = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=4),
            end_time=event.start_time + timedelta(hours=8),
        )
        session.time_slots.add(early_slot, late_slot)
        start = event.start_time + timedelta(hours=1)
        end = event.start_time + timedelta(hours=5)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                slot_violations=[
                    PreferredSlotViolationDTO(
                        session_pk=session.pk,
                        session_title=session.title,
                        scheduled_start=start,
                        scheduled_end=end,
                        preferred_slots=[
                            PreferredSlotRangeDTO(
                                start_time=early_slot.start_time,
                                end_time=early_slot.end_time,
                            ),
                            PreferredSlotRangeDTO(
                                start_time=late_slot.start_time,
                                end_time=late_slot.end_time,
                            ),
                        ],
                        track_name=None,
                        manager_names=[],
                    )
                ],
            ),
        )

    def test_skips_session_with_no_preferred_slots(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                slot_violations=[],
            ),
        )
