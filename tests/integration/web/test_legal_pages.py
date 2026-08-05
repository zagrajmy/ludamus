from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from ludamus.gates.web.django.legal import legal_document
from tests.integration.utils import assert_response


class TestLegalDocumentView:
    def test_privacy_policy(self, client):
        response = client.get(reverse("privacy-policy"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="legal/document.html",
            # The rendered document is thousands of characters; the e2e suite
            # asserts what a reader actually sees.
            context_data={"title": "Privacy Policy", "content": ANY},
        )

    def test_terms_of_service(self, client):
        response = client.get(reverse("terms-of-service"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="legal/document.html",
            context_data={"title": "Terms of Service", "content": ANY},
        )

    def test_unknown_slug_is_not_read_from_disk(self):
        # Both URLs name their slug, so this guard is what keeps a future third
        # entry from turning into a read of an arbitrary path.
        request = RequestFactory().get("/whatever/")

        with pytest.raises(Http404):
            legal_document(request, slug="../../../etc/passwd")


class TestOldFlatpageUrls:
    @pytest.mark.parametrize(
        ("old", "new"),
        (
            ("/page//privacy-policy/", "/privacy-policy/"),
            ("/page/privacy-policy/", "/privacy-policy/"),
            ("/page//terms-of-service/", "/terms-of-service/"),
            ("/page/terms-of-service/", "/terms-of-service/"),
        ),
    )
    def test_redirects_permanently(self, client, old, new):
        response = client.get(old)

        assert_response(response, HTTPStatus.MOVED_PERMANENTLY, url=new)
