from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from ludamus.pacts import EventDTO
from ludamus.pacts.legacy import SessionDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    make_timetable_session,
)


class TestTimetableSessionDetailPartView:
    """Tests for /panel/event/<slug>/timetable/parts/session/<pk>/ partial."""

    @staticmethod
    def get_url(event, pk):
        return reverse(
            "panel:timetable-session-detail-part", kwargs={"slug": event.slug, "pk": pk}
        )

    def test_redirects_anonymous_user_to_login(self, client, event, session):
        url = self.get_url(event, session.pk)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event, session):
        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse(
            "panel:timetable-session-detail-part",
            kwargs={"slug": "nonexistent", "pk": 1},
        )

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_redirects_on_nonexistent_session(self, panel_client, event):
        response = panel_client.get(self.get_url(event, 999999))

        assert_response(
            response, HTTPStatus.FOUND, url=f"/panel/event/{event.slug}/timetable/"
        )

    def test_ok_returns_partial_template(self, panel_client, event, proposal_category):
        session = make_timetable_session(proposal_category, participants_limit=10)

        response = panel_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-session-detail.html",
            context_data={
                "session": SessionDTO.model_validate(session),
                "agenda_item": None,
                "facilitators": [],
                "time_slots": [],
                "time_slots_json": "[]",
                "duration_minutes": 60,
                "slug": event.slug,
                "event": EventDTO.model_validate(event),
                "back_url": reverse(
                    "panel:timetable-browse-pane-part", kwargs={"slug": event.slug}
                ),
            },
        )

    def test_redirects_when_session_belongs_to_other_sphere(self, panel_client, event):
        other_event = EventFactory()
        other_category = ProposalCategoryFactory(event=other_event)
        other_session = SessionFactory(
            category=other_category, title="Secret session from another sphere"
        )

        response = panel_client.get(self.get_url(event, other_session.pk))

        assert_response(
            response, HTTPStatus.FOUND, url=f"/panel/event/{event.slug}/timetable/"
        )

    def test_back_url_preserves_filters(self, panel_client, event, proposal_category):
        session = make_timetable_session(proposal_category, participants_limit=10)

        response = panel_client.get(
            self.get_url(event, session.pk),
            {
                "category": "5",
                "max_duration": "60",
                "search": "magic",
                "date": "2026-09-04",
            },
        )

        assert response.status_code == HTTPStatus.OK
        back_url = response.context["back_url"]
        assert "category=5" in back_url
        assert "max_duration=60" in back_url
        assert "search=magic" in back_url
        assert "date=2026-09-04" in back_url

    def test_shows_session_title(self, panel_client, event, proposal_category):
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            title="My Awesome Session",
            participants_limit=10,
            min_age=0,
        )

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        assert response.context["session"].title == "My Awesome Session"

    def test_links_to_proposal_detail_page(
        self, panel_client, event, proposal_category
    ):
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            title="Linked Session",
            participants_limit=10,
            min_age=0,
        )
        proposal_url = reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        )

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        assert f'href="{proposal_url}"' in response.content.decode()

    def test_shows_agenda_item_when_scheduled(
        self, panel_client, event, proposal_category
    ):
        space = SpaceFactory(event=event)
        session = make_timetable_session(proposal_category, participants_limit=10)
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        assert response.context["agenda_item"] is not None
        assert response.context["agenda_item"].space_id == space.pk

    def test_agenda_item_is_none_when_unscheduled(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(proposal_category, participants_limit=10)

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        assert response.context["agenda_item"] is None

    def test_scheduled_unconfirmed_offers_confirm_button(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(proposal_category, participants_limit=10)
        AgendaItemFactory(
            session=session,
            space=SpaceFactory(event=event),
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Confirm program item" in content
        assert "Undo confirmation" not in content

    def test_scheduled_confirmed_offers_undo_button(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(proposal_category, participants_limit=10)
        agenda_item = AgendaItemFactory(
            session=session,
            space=SpaceFactory(event=event),
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )
        agenda_item.session_confirmed = True
        agenda_item.save()

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Undo confirmation" in content
        assert "Confirm program item" not in content

    def test_reassign_button_carries_confirmed_flag(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(proposal_category, participants_limit=10)
        AgendaItemFactory(
            session=session,
            space=SpaceFactory(event=event),
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
            session_confirmed=True,
        )

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        assert 'data-assign-confirmed="true"' in response.content.decode()

    def test_assign_button_of_unscheduled_session_is_unconfirmed(
        self, panel_client, event, proposal_category
    ):
        session = make_timetable_session(proposal_category, participants_limit=10)

        response = panel_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        assert 'data-assign-confirmed="false"' in response.content.decode()
