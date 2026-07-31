from datetime import timedelta
from http import HTTPStatus

from django.contrib.auth import get_user_model
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, Track
from tests.integration.conftest import (
    AgendaItemFactory,
    SpaceFactory,
    TimeSlotFactory,
    UserFactory,
)
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    make_overlapping_sessions,
    make_timetable_session,
    schedule_session,
)

User = get_user_model()


class TestTimetableConflictsPartView:
    """Tests for /panel/event/<slug>/timetable/parts/conflicts/ partial."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-conflicts-part", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-conflicts-part", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_event_not_found(response)

    def test_ok_returns_partial_template(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-conflict-panel.html",
            context_data={"conflicts": [], "slug": event.slug, "filter_track_pk": None},
        )

    def test_empty_conflicts_when_no_sessions(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["conflicts"] == []

    def test_detects_space_overlap_conflict(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        make_overlapping_sessions(event, proposal_category)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        conflict_types = [c.type for c in response.context["conflicts"]]
        assert "space_overlap" in conflict_types

    def test_slot_violation_does_not_appear_in_conflicts(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category)
        preferred = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=4),
            end_time=event.start_time + timedelta(hours=6),
        )
        session.time_slots.add(preferred)
        schedule_session(session, space, event.start_time)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["conflicts"] == []

    def test_cross_track_facilitator_conflict_has_attribution(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)

        manager_a = UserFactory()
        manager_b = UserFactory()

        track_a = Track.objects.create(
            event=event, name="Ścieżka A", slug="sciezka-a", is_public=True
        )
        track_a.managers.add(manager_a)

        track_b = Track.objects.create(
            event=event, name="Ścieżka B", slug="sciezka-b", is_public=True
        )
        track_b.managers.add(manager_b)

        space_a = SpaceFactory(event=event)
        space_b = SpaceFactory(event=event)

        session_a = make_timetable_session(proposal_category)
        session_b = make_timetable_session(proposal_category)

        # Shared facilitator
        shared_facilitator = Facilitator.objects.create(
            event=event, display_name="Wspólny prowadzący", slug="wspolny"
        )
        session_a.facilitators.add(shared_facilitator)
        session_b.facilitators.add(shared_facilitator)

        session_a.tracks.add(track_a)
        session_b.tracks.add(track_b)

        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(
            session=session_a, space=space_a, start_time=start, end_time=end
        )
        AgendaItemFactory(
            session=session_b, space=space_b, start_time=start, end_time=end
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        conflicts = response.context["conflicts"]
        facilitator_conflicts = [
            c for c in conflicts if c.type == "facilitator_overlap"
        ]
        assert len(facilitator_conflicts) == 1
        conflict = facilitator_conflicts[0]
        assert conflict.track_name is not None
        assert conflict.manager_names != []
