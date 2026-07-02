from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Space
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
        time_slot,
    ):
        sphere.managers.add(active_user)
        empty_space = SpaceFactory(event=event, name="Empty Hall")
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
        time_slot,
    ):
        sphere.managers.add(active_user)
        empty_space = SpaceFactory(event=event, name="Empty Hall")
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

    def test_timetable_scoped_to_node(
        self, authenticated_client, active_user, sphere, event, session, time_slot
    ):
        sphere.managers.add(active_user)
        parent = Space.objects.create(event=event, name="Hall", slug="hall")
        leaf = Space.objects.create(
            event=event, parent=parent, name="Room", slug="room"
        )
        AgendaItemFactory(
            session=session,
            space=leaf,
            start_time=time_slot.start_time,
            end_time=time_slot.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(
            self.timetable_url(event), {"scope": parent.pk}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/print/timetable.html",
            context_data={"document": ANY},
        )
        content = response.content.decode()
        assert "Hall" in content  # scope name in the header
        assert session.title in content

    def test_unknown_scope_redirects_with_message(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.timetable_url(event), {"scope": "987654"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=reverse("panel:timetable", kwargs={"slug": event.slug}),
        )


class TestPrintMaterialsPageView:
    @staticmethod
    def url(event):
        return reverse("panel:print-materials", kwargs={"slug": event.slug})

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_renders_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/print-materials.html",
            context_data=ANY,
        )
        content = response.content.decode()
        assert "Print timetable" in content
        assert "Print door cards" in content
        assert response.context_data["active_nav"] == "print"

    def test_scope_menu_lists_non_leaf_nodes(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        parent = Space.objects.create(event=event, name="Hall", slug="hall")
        Space.objects.create(event=event, parent=parent, name="Room", slug="room")

        response = authenticated_client.get(self.url(event))

        content = response.content.decode()
        assert "Hall" in content  # scope option label (non-leaf node)
        assert f"?scope={parent.pk}" in content  # scoped print link
