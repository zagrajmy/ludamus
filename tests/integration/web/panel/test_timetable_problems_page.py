from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse
from django.utils.timezone import get_current_timezone, localtime

from ludamus.pacts import EventDTO
from ludamus.pacts.availability import AvailabilityDTO, DayPart, part_of, programme_date
from ludamus.pacts.chronology import (
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    OfferedTimeViolationDTO,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionAvailabilityFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    make_overlapping_sessions,
    make_room_and_facilitator_clash,
    make_timetable_session,
    schedule_session,
    timetable_tab_urls,
)

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
    def expected_context(event, *, stats, conflicts_grouped, time_violations):
        return {
            "current_event": EventDTO.model_validate(event),
            "events": [EventDTO.model_validate(event)],
            "is_proposal_active": False,
            "stats": stats,
            "active_nav": "timetable",
            "conflicts_grouped": conflicts_grouped,
            "time_violations": time_violations,
            "slug": event.slug,
            "tab_urls": timetable_tab_urls(event),
            "active_tab": "problems",
        }

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-problems", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_ok_returns_problems_template(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

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
                time_violations=[],
            ),
        )

    def test_lists_space_overlap_conflict(self, panel_client, event, proposal_category):
        _, (session_a, session_b) = make_overlapping_sessions(event, proposal_category)

        response = panel_client.get(self.get_url(event))

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
                time_violations=[],
            ),
        )

    def test_lists_room_and_facilitator_clash_of_one_pair_separately(
        self, panel_client, event, proposal_category
    ):
        _, (session_a, session_b), facilitator = make_room_and_facilitator_clash(
            event, proposal_category
        )

        response = panel_client.get(self.get_url(event))

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
                    ],
                    ConflictType.FACILITATOR_OVERLAP: [
                        ConflictDTO(
                            type=ConflictType.FACILITATOR_OVERLAP,
                            severity=ConflictSeverity.ERROR,
                            subject_session_title=session_a.title,
                            subject_session_pk=session_a.pk,
                            session_title=session_b.title,
                            session_pk=session_b.pk,
                            facilitator_name=facilitator.display_name,
                        )
                    ],
                },
                time_violations=[],
            ),
        )

    def test_lists_session_scheduled_at_a_time_nobody_offered(
        self, panel_client, event, proposal_category
    ):
        tz = get_current_timezone()
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        offered = AvailabilityDTO(
            day=programme_date(event.start_time, tz) + timedelta(days=1),
            part=part_of(event.start_time, tz),
        )
        SessionAvailabilityFactory(session=session, day=offered.day, part=offered.part)
        agenda_item = schedule_session(
            session=session, space=space, start=event.start_time
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                time_violations=[
                    OfferedTimeViolationDTO(
                        session_pk=session.pk,
                        session_title=session.title,
                        scheduled_start=agenda_item.start_time,
                        scheduled_end=agenda_item.end_time,
                        availability=[offered],
                        track_name=None,
                        manager_names=[],
                    )
                ],
            ),
        )

    def test_lists_every_time_the_facilitator_offered(
        self, panel_client, event, proposal_category
    ):
        tz = get_current_timezone()
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        start = event.start_time + timedelta(hours=1)
        end = start + timedelta(hours=4)
        part = part_of(start, tz)
        placed_day = programme_date(start, tz)
        first_offered = AvailabilityDTO(day=placed_day + timedelta(days=1), part=part)
        second_offered = AvailabilityDTO(day=placed_day + timedelta(days=2), part=part)
        for entry in (second_offered, first_offered):
            SessionAvailabilityFactory(session=session, day=entry.day, part=entry.part)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                time_violations=[
                    OfferedTimeViolationDTO(
                        session_pk=session.pk,
                        session_title=session.title,
                        scheduled_start=start,
                        scheduled_end=end,
                        availability=[first_offered, second_offered],
                        track_name=None,
                        manager_names=[],
                    )
                ],
            ),
        )

    def test_skips_session_scheduled_at_an_offered_time(
        self, panel_client, event, proposal_category
    ):
        tz = get_current_timezone()
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        SessionAvailabilityFactory(
            session=session,
            day=programme_date(event.start_time, tz),
            part=part_of(event.start_time, tz),
        )
        schedule_session(session=session, space=space, start=event.start_time)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                time_violations=[],
            ),
        )

    def test_skips_session_running_past_midnight_out_of_the_offered_part(
        self, panel_client, event, proposal_category
    ):
        # A block is judged on the part it opens in, which is the one the
        # facilitator answered about — not the night it runs into.
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        start = localtime(event.start_time).replace(
            hour=23, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(hours=2)
        SessionAvailabilityFactory(
            session=session, day=start.date(), part=DayPart.EVENING
        )
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                time_violations=[],
            ),
        )

    def test_skips_session_with_no_availability(
        self, panel_client, event, proposal_category
    ):
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        schedule_session(session=session, space=space, start=event.start_time)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-problems.html",
            context_data=self.expected_context(
                event,
                stats=ONE_SCHEDULED_SESSION_STATS,
                conflicts_grouped={},
                time_violations=[],
            ),
        )
