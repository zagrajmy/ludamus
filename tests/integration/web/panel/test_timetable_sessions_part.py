from datetime import timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator
from ludamus.pacts import UNSCHEDULED_LIST_LIMIT
from ludamus.pacts.legacy import ProposalCategoryDTO, UnscheduledSessionDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    make_timetable_session,
)


class TestTimetableSessionListPartView:
    """Tests for /panel/event/<slug>/timetable/parts/sessions/ partial."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-sessions-part", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-sessions-part", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_ok_returns_partial_template(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-session-list.html",
            context_data={
                "sessions": [],
                "has_more": False,
                "limit": UNSCHEDULED_LIST_LIMIT,
                "categories": [],
                "search": "",
                "category_pk": None,
                "max_duration_minutes": None,
                "duration_chips": [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)],
                "filter_track_pk": None,
                "date_selection": "all",
                "slug": event.slug,
            },
        )

    def test_lists_unscheduled_accepted_sessions(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )

        response = panel_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert session.pk in session_pks

    def test_excludes_non_accepted_sessions(
        self, panel_client, event, proposal_category
    ):
        accepted = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        pending = make_timetable_session(proposal_category, participants_limit=10)
        rejected = make_timetable_session(
            proposal_category, status="rejected", participants_limit=10
        )

        response = panel_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert accepted.pk in session_pks
        assert pending.pk not in session_pks
        assert rejected.pk not in session_pks

    def test_excludes_scheduled_sessions(self, panel_client, event, proposal_category):
        space = SpaceFactory(event=event)
        session = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = panel_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert session.pk not in session_pks

    def test_search_filters_by_title(self, panel_client, event, proposal_category):
        matching = SessionFactory(
            category=proposal_category,
            status="accepted",
            title="HTMX Magic Workshop",
            participants_limit=10,
            min_age=0,
        )
        other = SessionFactory(
            category=proposal_category,
            status="accepted",
            title="Board Games Evening",
            participants_limit=10,
            min_age=0,
        )

        response = panel_client.get(self.get_url(event), {"search": "magic"})

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert matching.pk in session_pks
        assert other.pk not in session_pks

    def test_facilitator_filter_narrows_the_unassigned_list(
        self, panel_client, event, proposal_category
    ):
        hers = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        hers.facilitators.add(alice)

        response = panel_client.get(self.get_url(event), {"facilitator": str(alice.pk)})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-session-list.html",
            context_data={
                "sessions": [
                    UnscheduledSessionDTO(
                        pk=hers.pk,
                        title=hers.title,
                        display_name=hers.display_name,
                        category_name=proposal_category.name,
                        category_pk=proposal_category.pk,
                        duration_minutes=0,
                        participants_limit=10,
                    )
                ],
                "has_more": False,
                "limit": UNSCHEDULED_LIST_LIMIT,
                "categories": [ProposalCategoryDTO.model_validate(proposal_category)],
                "search": "",
                "category_pk": None,
                "max_duration_minutes": None,
                "duration_chips": [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)],
                "filter_track_pk": None,
                "date_selection": "all",
                "slug": event.slug,
            },
        )

    def test_category_filter(self, panel_client, event, proposal_category):
        other_category = ProposalCategoryFactory(event=event)
        matching = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        other = SessionFactory(
            category=other_category, status="accepted", participants_limit=10, min_age=0
        )

        response = panel_client.get(
            self.get_url(event), {"category": str(proposal_category.pk)}
        )

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert matching.pk in session_pks
        assert other.pk not in session_pks

    @pytest.mark.parametrize("max_duration", ("abc", "-1", "0", ""))
    def test_invalid_max_duration_param_does_not_raise(
        self, panel_client, event, max_duration
    ):
        response = panel_client.get(self.get_url(event), {"max_duration": max_duration})

        assert response.status_code == HTTPStatus.OK

    def test_date_filter_keeps_sessions_with_slot_on_that_date(
        self, panel_client, event, proposal_category
    ):
        slot_day_one = TimeSlotFactory(event=event)
        slot_day_two = TimeSlotFactory(
            event=event, start_time=event.start_time + timedelta(days=1)
        )
        on_day_one = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        on_day_one.time_slots.add(slot_day_one)
        on_day_two = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        on_day_two.time_slots.add(slot_day_two)
        anytime = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )

        response = panel_client.get(
            self.get_url(event), {"date": slot_day_one.start_time.date().isoformat()}
        )

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert on_day_one.pk in session_pks
        assert anytime.pk in session_pks
        assert on_day_two.pk not in session_pks

    def test_invalid_date_param_does_not_filter(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        session.time_slots.add(
            TimeSlotFactory(
                event=event, start_time=event.start_time + timedelta(days=1)
            )
        )

        response = panel_client.get(self.get_url(event), {"date": "not-a-date"})

        assert response.status_code == HTTPStatus.OK
        session_pks = [s.pk for s in response.context["sessions"]]
        assert session.pk in session_pks

    def test_all_date_param_does_not_filter_and_stays_in_links(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(
            proposal_category, status="accepted", participants_limit=10
        )
        session.time_slots.add(
            TimeSlotFactory(
                event=event, start_time=event.start_time + timedelta(days=1)
            )
        )

        response = panel_client.get(self.get_url(event), {"date": "all"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-session-list.html",
            context_data={
                "sessions": [
                    UnscheduledSessionDTO(
                        pk=session.pk,
                        title=session.title,
                        display_name=session.display_name,
                        category_name=proposal_category.name,
                        category_pk=proposal_category.pk,
                        duration_minutes=0,
                        participants_limit=10,
                    )
                ],
                "has_more": False,
                "limit": UNSCHEDULED_LIST_LIMIT,
                "categories": [ProposalCategoryDTO.model_validate(proposal_category)],
                "search": "",
                "category_pk": None,
                "max_duration_minutes": None,
                "duration_chips": [("≤30 min", 30), ("≤60 min", 60), ("≤90 min", 90)],
                "filter_track_pk": None,
                "date_selection": "all",
                "slug": event.slug,
            },
            contains="date=all",
        )

    def test_caps_results_at_limit_and_flags_has_more(
        self, panel_client, event, proposal_category
    ):
        for index in range(UNSCHEDULED_LIST_LIMIT + 1):
            SessionFactory(
                category=proposal_category,
                status="accepted",
                title=f"Session {index:03d}",
                participants_limit=10,
                min_age=0,
            )

        response = panel_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert len(response.context["sessions"]) == UNSCHEDULED_LIST_LIMIT
        assert response.context["has_more"] is True
        assert response.context["limit"] == UNSCHEDULED_LIST_LIMIT
