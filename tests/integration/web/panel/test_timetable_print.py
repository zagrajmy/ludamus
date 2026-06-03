from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from tests.integration.conftest import AgendaItemFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _assert_pdf(response, *, filename_part):
    assert response.status_code == HTTPStatus.OK, response.status_code
    assert response["Content-Type"] == "application/pdf"
    assert filename_part in response["Content-Disposition"]
    assert response.content[:5] == b"%PDF-"


class TestTimetablePrintView:
    @staticmethod
    def timetable_url(event):
        return reverse("panel:timetable-print", kwargs={"slug": event.slug})

    @staticmethod
    def door_cards_url(event):
        return reverse("panel:timetable-print-door-cards", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.timetable_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.timetable_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_timetable_pdf_for_sphere_manager(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        session,
        space,
        time_slot,
    ):
        sphere.managers.add(active_user)
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(self.timetable_url(event))

        _assert_pdf(response, filename_part=f"{event.slug}-timetable.pdf")
        assert time_slot is not None

    def test_door_cards_pdf_for_sphere_manager(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        session,
        space,
        time_slot,
    ):
        sphere.managers.add(active_user)
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(self.door_cards_url(event))

        _assert_pdf(response, filename_part=f"{event.slug}-door-cards.pdf")
        assert time_slot is not None
