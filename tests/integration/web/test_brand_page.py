from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse

from tests.integration.utils import assert_response


class TestBrandPageView:
    URL = reverse("web:brand")

    def test_ok(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"view": ANY},
            template_name=["brand.html"],
            contains=[
                "Logo & Brand Guidelines",
                "logo-lockup",
                "tuck-in",
                "#f85a3c",
                "favicon-dev.svg",
            ],
        )
