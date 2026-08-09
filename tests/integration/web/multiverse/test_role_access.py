from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import Announcement, SphereMembership
from ludamus.pacts.multiverse import SphereRole
from tests.integration.utils import assert_response
from tests.integration.web.multiverse.helpers import (
    assert_not_a_sphere_manager,
    sphere_panel_context,
)


@pytest.fixture(name="comms_client")
def comms_client_fixture(authenticated_client, active_user, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.COMMS
    )
    return authenticated_client


@pytest.mark.django_db
class TestCommsRoleOnSpherePanel:
    def test_comms_member_reads_a_sphere_panel_page(self, comms_client):
        response = comms_client.get(reverse("multiverse:panel:announcements"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/list.html",
            context_data={
                **sphere_panel_context(active_tab="announcements"),
                "announcements": [],
            },
        )

    def test_comms_member_cannot_post(self, comms_client, sphere):
        response = comms_client.post(
            reverse("multiverse:panel:announcement-create"),
            data={"title": "Errata", "content": "body", "is_published": "on"},
        )

        assert_not_a_sphere_manager(response)
        assert not Announcement.objects.filter(sphere=sphere).exists()
