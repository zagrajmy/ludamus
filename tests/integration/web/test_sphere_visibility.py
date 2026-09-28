from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.pacts.multiverse import SphereVisibility
from tests.integration.utils import assert_response, assert_response_404

URL = reverse("web:index")


def _empty_feed(*, can_create_encounter=False):
    return {
        "announcements": [],
        "can_create_encounter": can_create_encounter,
        "past": [],
        "upcoming": [],
        "view": ANY,
    }


@pytest.fixture(name="private_sphere")
def private_sphere_fixture(non_root_sphere):
    non_root_sphere.visibility = SphereVisibility.PRIVATE
    non_root_sphere.save()
    return non_root_sphere


class TestPrivateSphere:
    def test_sends_an_anonymous_visitor_to_sign_in(self, client, private_sphere):
        response = client.get(URL, HTTP_HOST=private_sphere.site.domain)

        assert_response(response, HTTPStatus.FOUND, url="/crowd/login-required/?next=/")

    def test_hides_itself_from_a_signed_in_stranger(
        self, authenticated_client, private_sphere
    ):
        response = authenticated_client.get(URL, HTTP_HOST=private_sphere.site.domain)

        assert_response_404(response)

    def test_opens_for_its_member(
        self, authenticated_client, active_user, private_sphere
    ):
        private_sphere.managers.add(active_user)

        response = authenticated_client.get(URL, HTTP_HOST=private_sphere.site.domain)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_empty_feed(can_create_encounter=True),
            template_name=["index.html"],
        )

    def test_keeps_sign_in_open(self, client, private_sphere):
        response = client.get(
            reverse("web:crowd:login-required"), HTTP_HOST=private_sphere.site.domain
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"next": ""},
            template_name="crowd/login_required.html",
        )


def test_unlisted_sphere_opens_for_anyone_with_the_link(client, non_root_sphere):
    non_root_sphere.visibility = SphereVisibility.UNLISTED
    non_root_sphere.save()

    response = client.get(URL, HTTP_HOST=non_root_sphere.site.domain)

    assert_response(
        response,
        HTTPStatus.OK,
        context_data=_empty_feed(),
        template_name=["index.html"],
    )
