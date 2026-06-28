import json
from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from tests.integration.conftest import (
    AgendaItemFactory,
    AreaFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    VenueFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTimetableConfirmView:
    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-confirm", kwargs={"slug": event.slug})

    @staticmethod
    def _scheduled_agenda_item(event, area):
        space = SpaceFactory(area=area)
        session = SessionFactory(
            category=ProposalCategoryFactory(event=event),
            status="scheduled",
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

        response = client.post(url, data={"agenda_item_pk": 1, "confirmed": "true"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event), data={"agenda_item_pk": 1, "confirmed": "true"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_missing_agenda_item_pk_returns_422(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), data={})

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_unknown_agenda_item_returns_422(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data={"agenda_item_pk": 99999, "confirmed": "true"}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_confirm_persists(
        self, authenticated_client, active_user, sphere, event, area
    ):
        sphere.managers.add(active_user)
        agenda_item = self._scheduled_agenda_item(event, area)

        response = authenticated_client.post(
            self.get_url(event),
            data={"agenda_item_pk": agenda_item.pk, "confirmed": "true"},
        )

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        agenda_item.refresh_from_db()
        assert agenda_item.session_confirmed is True

    def test_unconfirm_persists(
        self, authenticated_client, active_user, sphere, event, area
    ):
        sphere.managers.add(active_user)
        agenda_item = self._scheduled_agenda_item(event, area)
        agenda_item.session_confirmed = True
        agenda_item.save()

        response = authenticated_client.post(
            self.get_url(event),
            data={"agenda_item_pk": agenda_item.pk, "confirmed": "false"},
        )

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        agenda_item.refresh_from_db()
        assert agenda_item.session_confirmed is False

    def test_returns_422_for_agenda_item_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        other_area = AreaFactory(venue=VenueFactory(event=other_event))
        other_item = self._scheduled_agenda_item(other_event, other_area)

        response = authenticated_client.post(
            self.get_url(event),
            data={"agenda_item_pk": other_item.pk, "confirmed": "true"},
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_item.refresh_from_db()
        assert other_item.session_confirmed is False

    def test_invalid_confirmed_value_returns_422(
        self, authenticated_client, active_user, sphere, event, area
    ):
        sphere.managers.add(active_user)
        agenda_item = self._scheduled_agenda_item(event, area)

        response = authenticated_client.post(
            self.get_url(event),
            data={"agenda_item_pk": agenda_item.pk, "confirmed": "maybe"},
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        agenda_item.refresh_from_db()
        assert agenda_item.session_confirmed is False

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirm", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(
            url, data={"agenda_item_pk": 1, "confirmed": "true"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
