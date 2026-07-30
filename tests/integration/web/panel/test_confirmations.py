from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, Track
from ludamus.pacts import EventDTO
from ludamus.pacts.event import (
    ConfirmationDashboardDTO,
    ConfirmationOrganizerRowDTO,
    ConfirmationTrackRowDTO,
)
from ludamus.pacts.legacy import TrackDTO
from tests.integration.conftest import AgendaItemFactory, SessionFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _tab_urls(event):
    return {
        "timetable": reverse("panel:timetable", kwargs={"slug": event.slug}),
        "log": reverse("panel:timetable-log", kwargs={"slug": event.slug}),
        "overview": reverse("panel:timetable-overview", kwargs={"slug": event.slug}),
        "problems": reverse("panel:timetable-problems", kwargs={"slug": event.slug}),
        "confirmations": reverse(
            "panel:timetable-confirmations", kwargs={"slug": event.slug}
        ),
    }


def _empty_stats():
    return {
        "hosts_count": 0,
        "pending_proposals": 0,
        "rooms_count": 0,
        "scheduled_sessions": 0,
        "total_proposals": 0,
        "total_sessions": 0,
    }


class TestConfirmationsPageView:
    """Tests for /panel/event/<slug>/timetable/confirmations/."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-confirmations", kwargs={"slug": event.slug})

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
        url = reverse("panel:timetable-confirmations", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_returns_empty_dashboard(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": _empty_stats(),
                "active_nav": "timetable",
                "all_tracks": [],
                "managed_track_pks": set(),
                "filter_track_pk": None,
                "dashboard": ConfirmationDashboardDTO(
                    organizers=[],
                    tracks=[],
                    scheduled_count=0,
                    confirmed_count=0,
                    progress_pct=0,
                    claimed_facilitator_count=0,
                    unclaimed_facilitator_count=0,
                    without_facilitator_count=0,
                ),
                "slug": event.slug,
                "tab_urls": _tab_urls(event),
                "active_tab": "confirmations",
            },
        )

    def test_counts_confirmed_of_scheduled_per_organizer_and_track(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )
        track.managers.add(active_user)
        mine = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada", organizer=active_user
        )
        unclaimed = Facilitator.objects.create(
            event=event, display_name="Ben", slug="ben"
        )
        for facilitator, confirmed in ((mine, True), (mine, False), (unclaimed, False)):
            session = SessionFactory(category=proposal_category, status="accepted")
            session.facilitators.add(facilitator)
            session.tracks.add(track)
            AgendaItemFactory(session=session, session_confirmed=confirmed)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["dashboard"] == ConfirmationDashboardDTO(
            organizers=[
                ConfirmationOrganizerRowDTO(
                    organizer_id=None,
                    organizer_name="",
                    facilitator_count=1,
                    scheduled_count=1,
                    confirmed_count=0,
                    progress_pct=0,
                ),
                ConfirmationOrganizerRowDTO(
                    organizer_id=active_user.pk,
                    organizer_name=active_user.name,
                    facilitator_count=1,
                    scheduled_count=2,
                    confirmed_count=1,
                    progress_pct=50,
                ),
            ],
            tracks=[
                ConfirmationTrackRowDTO(
                    track_pk=track.pk,
                    track_name="RPG",
                    manager_names=[active_user.name],
                    facilitator_count=2,
                    scheduled_count=3,
                    confirmed_count=1,
                    progress_pct=33,
                )
            ],
            scheduled_count=3,
            confirmed_count=1,
            progress_pct=33,
            claimed_facilitator_count=1,
            unclaimed_facilitator_count=1,
            without_facilitator_count=0,
        )

    def test_reports_scheduled_sessions_that_have_no_facilitator(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = SessionFactory(category=proposal_category, status="accepted")
        AgendaItemFactory(session=session)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["dashboard"].without_facilitator_count == 1

    def test_selecting_a_track_keeps_it_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )

        response = authenticated_client.get(f"{self.get_url(event)}?track={track.pk}")

        assert response.status_code == HTTPStatus.OK
        assert response.context["filter_track_pk"] == track.pk
        assert response.context["all_tracks"] == [TrackDTO.model_validate(track)]

    def test_auto_selects_the_single_track_the_user_manages(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )
        track.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["filter_track_pk"] == track.pk
        assert response.context["managed_track_pks"] == {track.pk}

    def test_unconfirmed_agenda_item_is_not_counted_as_confirmed(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada", organizer=active_user
        )
        session = SessionFactory(category=proposal_category, status="accepted")
        session.facilitators.add(facilitator)
        AgendaItemFactory(session=session, session_confirmed=False)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["dashboard"].confirmed_count == 0
        assert response.context["dashboard"].scheduled_count == 1
