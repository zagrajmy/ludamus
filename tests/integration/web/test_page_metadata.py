import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from tests.integration.conftest import PNG_BYTES, EncounterFactory, EventFactory

PRODUCT_PITCH = "Zagrajmy brings players and organizers together."


def _title(response):
    match = re.search(r"<title>(.*?)</title>", response.content.decode(), re.DOTALL)
    assert match, "no <title> in response"
    return " ".join(match.group(1).split())


def _meta(response, attribute, value):
    match = re.search(
        rf'<meta[^>]+{attribute}="{value}"[^>]+content="([^"]*)"',
        response.content.decode(),
    )
    assert match, f"no <meta {attribute}={value}> in response"
    return " ".join(match.group(1).split())


def _descriptions(response):
    return [
        _meta(response, "name", "description"),
        _meta(response, "property", "og:description"),
        _meta(response, "name", "twitter:description"),
    ]


class TestPageTitle:
    def test_root_sphere_title_omits_the_brand_tail(self, client, sphere):
        response = client.get(reverse("web:events"))

        assert _title(response).endswith(f"• {sphere.name}")

    def test_sub_sphere_title_ends_with_the_brand(
        self, client, sphere, non_root_sphere
    ):
        response = client.get(
            reverse("web:events"), HTTP_HOST=non_root_sphere.site.domain
        )

        assert _title(response).endswith(f"• {non_root_sphere.name} • {sphere.name}")


class TestMetaDescription:
    def test_listing_page_describes_the_product(self, client):
        response = client.get(reverse("web:events"))

        assert all(
            description.endswith(PRODUCT_PITCH)
            for description in _descriptions(response)
        )

    def test_event_page_describes_the_event(self, client, sphere):
        event = EventFactory(sphere=sphere, description="Konwent gier w Krakowie")

        response = client.get(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        )

        assert _descriptions(response) == ["Konwent gier w Krakowie"] * 3

    def test_encounter_page_describes_the_encounter(self, client, sphere):
        encounter = EncounterFactory(
            sphere=sphere, place="Kraków", description="Kolacja i planszówki"
        )

        response = client.get(
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            )
        )

        description = _meta(response, "name", "description")
        assert "Kraków" in description
        assert "Kolacja i planszówki" in description
        assert _descriptions(response) == [description] * 3


class TestMetaImage:
    def test_defaults_to_an_absolute_brand_url(self, client):
        response = client.get(reverse("web:events"))

        assert _meta(response, "property", "og:image").startswith(
            "http://testserver/static/"
        )

    def test_event_cover_wins_over_the_brand_image(self, client, sphere):
        event = EventFactory(sphere=sphere)
        event.cover_image = SimpleUploadedFile("cover.png", PNG_BYTES, "image/png")
        event.save()

        response = client.get(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        )

        assert _meta(response, "property", "og:image").endswith(event.cover_image.url)
