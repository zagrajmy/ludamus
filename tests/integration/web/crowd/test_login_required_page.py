from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse

from tests.integration.utils import assert_response


class TestLoginRequiredPageView:
    URL = reverse("web:crowd:login-required")

    def test_ok(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["crowd/login_required.html"],
            context_data={
                "view": ANY,
                "next": "",
                "show_icon": True,
                "text": "",
                "extra_class": "",
            },
        )

    def test_ok_with_next_url(self, client):
        next_url = "/event/test-event"
        response = client.get(self.URL + f"?next={next_url}")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["crowd/login_required.html"],
            context_data={
                "view": ANY,
                "next": "/event/test-event",
                "show_icon": True,
                "text": "",
                "extra_class": "",
            },
        )
