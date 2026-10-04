import json
from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
)


class TestTimetableConfirmView:
    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-confirm", kwargs={"slug": event.slug})

    @staticmethod
    def _scheduled_agenda_item(event):
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=ProposalCategoryFactory(event=event),
            status="accepted",
            participants_limit=5,
            min_age=0,
        )
        return AgendaItemFactory(
            session=session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={"session_pk": 1, "confirmed": "true"})

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event), data={"session_pk": 1, "confirmed": "true"}
        )

        assert_not_a_manager(response)

    def test_missing_session_pk_returns_422(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={})

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_unknown_session_returns_422(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event), data={"session_pk": 99999, "confirmed": "true"}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_confirm_persists(self, panel_client, event):
        agenda_item = self._scheduled_agenda_item(event)

        response = panel_client.post(
            self.get_url(event),
            data={"session_pk": agenda_item.session.pk, "confirmed": "true"},
        )

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        agenda_item.refresh_from_db()
        agenda_item.session.refresh_from_db()
        assert agenda_item.session.schedule_confirmed is True
        assert agenda_item.session_confirmed is True

    def test_unconfirm_persists(self, panel_client, event):
        agenda_item = self._scheduled_agenda_item(event)
        agenda_item.session.schedule_confirmed = True
        agenda_item.session.save()
        agenda_item.session_confirmed = True
        agenda_item.save()

        response = panel_client.post(
            self.get_url(event),
            data={"session_pk": agenda_item.session.pk, "confirmed": "false"},
        )

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        agenda_item.refresh_from_db()
        agenda_item.session.refresh_from_db()
        assert agenda_item.session.schedule_confirmed is False
        assert agenda_item.session_confirmed is False

    def test_returns_422_for_a_session_not_on_the_timetable(self, panel_client, event):
        session = SessionFactory(
            category=ProposalCategoryFactory(event=event), status="accepted"
        )

        response = panel_client.post(
            self.get_url(event), data={"session_pk": session.pk, "confirmed": "true"}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        session.refresh_from_db()
        assert session.schedule_confirmed is False

    def test_returns_422_for_session_from_another_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        other_item = self._scheduled_agenda_item(other_event)

        response = panel_client.post(
            self.get_url(event),
            data={"session_pk": other_item.session.pk, "confirmed": "true"},
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_item.session.refresh_from_db()
        assert other_item.session.schedule_confirmed is False

    def test_invalid_confirmed_value_returns_422(self, panel_client, event):
        agenda_item = self._scheduled_agenda_item(event)

        response = panel_client.post(
            self.get_url(event),
            data={"session_pk": agenda_item.session.pk, "confirmed": "maybe"},
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        agenda_item.session.refresh_from_db()
        assert agenda_item.session.schedule_confirmed is False

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-confirm", kwargs={"slug": "nonexistent"})

        response = panel_client.post(url, data={"session_pk": 1, "confirmed": "true"})

        assert_event_not_found(response)
