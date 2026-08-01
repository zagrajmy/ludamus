from datetime import timedelta
from http import HTTPStatus

from django.contrib.auth import get_user_model
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, Track
from ludamus.pacts.chronology import ConflictDTO, ConflictSeverity, ConflictType
from tests.integration.conftest import AgendaItemFactory, SpaceFactory, UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    make_overlapping_sessions,
    make_timetable_session,
    schedule_outside_preferred_slot,
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

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-conflicts-part", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_ok_returns_partial_template(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-conflict-panel.html",
            context_data={"conflicts": [], "slug": event.slug, "filter_track_pk": None},
        )

    def test_detects_space_overlap_conflict(
        self, panel_client, event, proposal_category
    ):
        _space, (subject, occupier) = make_overlapping_sessions(
            event, proposal_category
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-conflict-panel.html",
            context_data={
                "conflicts": [
                    ConflictDTO(
                        type=ConflictType.SPACE_OVERLAP,
                        severity=ConflictSeverity.ERROR,
                        subject_session_title=subject.title,
                        subject_session_pk=subject.pk,
                        session_title=occupier.title,
                        session_pk=occupier.pk,
                    )
                ],
                "slug": event.slug,
                "filter_track_pk": None,
            },
        )

    def test_slot_violation_does_not_appear_in_conflicts(
        self, panel_client, event, proposal_category
    ):
        schedule_outside_preferred_slot(
            event=event, category=proposal_category, space=SpaceFactory(event=event)
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-conflict-panel.html",
            context_data={"conflicts": [], "slug": event.slug, "filter_track_pk": None},
        )

    def test_cross_track_facilitator_conflict_has_attribution(
        self, panel_client, event, proposal_category
    ):
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

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-conflict-panel.html",
            context_data={
                "conflicts": [
                    ConflictDTO(
                        type=ConflictType.FACILITATOR_OVERLAP,
                        severity=ConflictSeverity.ERROR,
                        subject_session_title=session_a.title,
                        subject_session_pk=session_a.pk,
                        session_title=session_b.title,
                        session_pk=session_b.pk,
                        facilitator_name=shared_facilitator.display_name,
                        track_name=track_b.name,
                        manager_names=[manager_b.name],
                    )
                ],
                "slug": event.slug,
                "filter_track_pk": None,
            },
        )
