from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.gates.web.django.create_options import encounter_option, event_option
from ludamus.pacts.sphere import SphereVisibility
from tests.integration.utils import assert_response, assert_response_404

URL = reverse("web:index")


def _empty_feed(*, create_options=()):
    return {
        "announcements": [],
        "create_options": create_options,
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
            context_data=_empty_feed(
                create_options=(event_option(), encounter_option())
            ),
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
            template_name="user/login_required.html",
        )

    def test_lets_a_visitor_pick_the_language_of_the_sign_in_page(
        self, client, private_sphere
    ):
        response = client.post(
            reverse("set_language"),
            {"language": "pl", "next": "/crowd/login-required/"},
            HTTP_HOST=private_sphere.site.domain,
        )

        assert_response(response, HTTPStatus.FOUND, url="/crowd/login-required/")
        assert response.cookies["django_language"].value == "pl"


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
