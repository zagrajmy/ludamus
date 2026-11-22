from http import HTTPStatus

import pytest
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from ludamus.gates.web.django.pages import CONTENT_DIR, content_page
from tests.integration.utils import assert_response


class TestContentPageView:
    @pytest.mark.parametrize(
        ("slug", "title"),
        (
            ("privacy-policy", "Privacy Policy"),
            ("terms-of-service", "Terms of Service"),
        ),
    )
    def test_renders_the_file_from_disk(self, *, client, slug, title):
        response = client.get(reverse(slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="content/page.html",
            context_data={
                "title": title,
                "document": (
                    (CONTENT_DIR / f"{slug}.md")
                    .read_text(encoding="utf-8")
                    .replace("$staff_email", "staff@zagrajmy.net")
                ),
            },
        )

    def test_terms_name_the_contact_point_from_settings(self, *, client, settings):
        settings.STAFF_EMAIL = "kontakt@example.org"

        response = client.get(reverse("terms-of-service"))

        document = response.context_data["document"]
        assert "**kontakt@example.org**" in document
        assert "$staff_email" not in document

    def test_unknown_slug_is_not_read_from_disk(self):
        # Both URLs name their slug, so this guard is what keeps a future third
        # entry from turning into a read of an arbitrary path.
        request = RequestFactory().get("/whatever/")

        with pytest.raises(Http404):
            content_page(request, slug="../../../etc/passwd")


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
    def test_redirects_permanently(self, *, client, old, new):
        response = client.get(old)

        assert_response(response, HTTPStatus.MOVED_PERMANENTLY, url=new)
