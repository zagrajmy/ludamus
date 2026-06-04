from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from tests.integration.conftest import AgendaItemFactory, SpaceFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


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

    def test_timetable_page_for_sphere_manager(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        session,
        space,
        area,
        time_slot,
    ):
        sphere.managers.add(active_user)
        empty_space = SpaceFactory(area=area, name="Empty Hall")
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=time_slot.start_time,
            end_time=time_slot.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(self.timetable_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/print/timetable.html",
            context_data={"document": ANY},
        )
        content = response.content.decode()
        assert session.title in content
        assert empty_space.name in content  # empty room is still a column
        assert "—" in content  # its empty cell renders a visible gap marker

    def test_door_cards_page_for_sphere_manager(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        session,
        space,
        area,
        time_slot,
    ):
        sphere.managers.add(active_user)
        empty_space = SpaceFactory(area=area, name="Empty Hall")
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=time_slot.start_time,
            end_time=time_slot.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(self.door_cards_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/print/door-cards.html",
            context_data={"document": ANY},
        )
        content = response.content.decode()
        assert space.name in content
        # the empty room's card shows the slot as a free gap
        assert empty_space.name in content
        assert "Free slot" in content

    def test_timetable_scoped_to_venue(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        session,
        space,
        venue,
        time_slot,
    ):
        sphere.managers.add(active_user)
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=time_slot.start_time,
            end_time=time_slot.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(
            self.timetable_url(event), {"venue": venue.slug}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/print/timetable.html",
            context_data={"document": ANY},
        )
        content = response.content.decode()
        assert venue.name in content  # scope name in the header
        assert session.title in content

    def test_timetable_scoped_to_area(
        self,
        authenticated_client,
        active_user,
        sphere,
        event,
        session,
        space,
        venue,
        area,
        time_slot,
    ):
        sphere.managers.add(active_user)
        AgendaItemFactory(
            session=session,
            space=space,
            start_time=time_slot.start_time,
            end_time=time_slot.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(
            self.timetable_url(event), {"venue": venue.slug, "area": area.slug}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/print/timetable.html",
            context_data={"document": ANY},
        )
        content = response.content.decode()
        assert area.name in content  # area is the scope name
        assert session.title in content

    def test_unknown_scope_redirects_with_message(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.timetable_url(event), {"venue": "does-not-exist"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue or area not found.")],
            url=reverse("panel:timetable", kwargs={"slug": event.slug}),
        )
