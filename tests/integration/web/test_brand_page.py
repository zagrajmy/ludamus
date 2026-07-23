from http import HTTPStatus
from unittest.mock import ANY

from django.test import override_settings
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

    @override_settings(IS_STAGING=True)
    def test_staging_favicon(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"view": ANY},
            template_name=["brand.html"],
            contains="favicon-staging.svg",
            not_contains="favicon-dev.svg",
        )

    @override_settings(IS_PRODUCTION=True)
    def test_production_favicon(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"view": ANY},
            template_name=["brand.html"],
            contains="/static/favicon.svg",
            not_contains="favicon-dev.svg",
        )
