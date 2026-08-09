from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import EventBan, SphereMembership
from ludamus.pacts.multiverse import SphereRole
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import assert_not_a_manager, panel_context


@pytest.fixture(name="comms_client")
def comms_client_fixture(authenticated_client, active_user, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.COMMS
    )
    return authenticated_client


@pytest.mark.django_db
class TestCommsRoleOnEventPanel:
    @staticmethod
    def _url(event):
        return reverse("panel:bans", kwargs={"slug": event.slug})

    def test_comms_member_reads_a_panel_page(self, comms_client, event):
        response = comms_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/bans.html",
            context_data={**panel_context(event, active_nav="bans"), "bans": []},
        )

    def test_comms_member_cannot_post(self, comms_client, event):
        # The identifier resolves, so a refusal here is the role talking and
        # not the form failing to find anyone.
        UserFactory(username="tm", email="tm@example.com", name="TM")

        response = comms_client.post(self._url(event), data={"identifier": "tm"})

        assert_not_a_manager(response)
        assert not EventBan.objects.exists()

    def test_superuser_holding_the_comms_role_still_posts(
        self, comms_client, active_user, event
    ):
        active_user.is_superuser = True
        active_user.save()
        troublemaker = UserFactory(username="tm", email="tm@example.com", name="TM")

        response = comms_client.post(self._url(event), data={"identifier": "tm"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "User banned from the event.")],
            url=self._url(event),
        )
        assert EventBan.objects.filter(event=event, user=troublemaker).exists()
