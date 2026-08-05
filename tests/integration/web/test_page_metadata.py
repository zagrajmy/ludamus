import re
from http import HTTPStatus
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

import ludamus
from tests.integration.conftest import PNG_BYTES, EncounterFactory, EventFactory
from tests.integration.utils import assert_response

PRODUCT_PITCH = (
    "A convention without spreadsheet chaos. Programme proposals, a schedule of"
    " rooms and tracks, sign-ups with seat limits and a waitlist."
)
LANDING_TITLE = "Zagrajmy • conventions and events"
LANDING_PITCH = (
    "Zagrajmy runs your event programme: proposals, review, the schedule, the"
    " event page, enrollment with waiting lists, and print."
    " Write to us: kontakt@zagrajmy.net"
)
TEMPLATES = Path(ludamus.__file__).parent / "templates"
TITLE_BLOCK = re.compile(
    r"{% block title %}(?:.*?){% endblock title %}|<title>(?:.*?)</title>", re.DOTALL
)


def _head(response, pattern):
    match = re.search(pattern, response.content.decode(), re.DOTALL)
    assert match, f"no {pattern} in response"
    return match.group(1)


def _title(response):
    return " ".join(_head(response, r"<title>(.*?)</title>").split())


# Raw for the tags base.html renders inline; object pages override with a
# standalone block, which djlint reflows onto its own line and so pads the
# attribute with whitespace.
def _meta_raw(response, attribute, value):
    return _head(response, rf'<meta[^>]+{attribute}="{value}"[^>]+content="([^"]*)"')


def _meta(response, attribute, value):
    return " ".join(_meta_raw(response, attribute, value).split())


def _titles(response):
    return [
        _title(response),
        _meta(response, "property", "og:title"),
        _meta(response, "name", "twitter:title"),
    ]


def _descriptions(response):
    return [
        _meta(response, "name", "description"),
        _meta(response, "property", "og:description"),
        _meta(response, "name", "twitter:description"),
    ]


def _get_ok(client, url, template_name, **extra):
    response = client.get(url, **extra)
    # Every test here reads <head>. What each view puts in the context is
    # asserted by that view's own test module, so this passes it through.
    assert_response(
        response,
        HTTPStatus.OK,
        context_data=response.context_data,
        template_name=template_name,
    )
    return response


class TestPageTitle:
    def test_root_sphere_title_omits_the_brand_tail(self, client, sphere):
        response = _get_ok(client, reverse("web:events"), ["index.html"])

        assert _title(response) == f"Events • {sphere.name}"

    def test_landing_page_titles_the_product(self, client, sphere):
        response = _get_ok(client, reverse("web:index"), ["landing_page.html"])

        assert _title(response) == LANDING_TITLE

    def test_sub_sphere_title_ends_with_the_brand(
        self, client, sphere, non_root_sphere
    ):
        response = _get_ok(
            client,
            reverse("web:events"),
            ["index.html"],
            HTTP_HOST=non_root_sphere.site.domain,
        )

        assert _title(response) == f"Events • {non_root_sphere.name} • Zagrajmy"

    def test_panel_page_title_names_the_event_it_manages(self, manager_client, event):
        response = _get_ok(
            manager_client,
            reverse("panel:event-index", kwargs={"slug": event.slug}),
            "panel/index.html",
        )

        assert _title(response) == f"Dashboard • {event.name}"

    def test_sphere_wide_panel_page_keeps_the_sphere(self, manager_client, sphere):
        response = _get_ok(
            manager_client,
            reverse("multiverse:panel:sphere-settings"),
            "multiverse/panel/sphere-settings.html",
        )

        assert _title(response) == f"Sphere settings • {sphere.name}"

    def test_print_document_title_names_the_document_and_the_event(
        self, manager_client, event, sphere
    ):
        response = _get_ok(
            manager_client,
            f'{reverse("web:chronology:event-print", kwargs={"slug": event.slug})}'
            "?material=door-cards",
            "chronology/print.html",
        )

        assert _title(response) == f"{event.name} • Print • {sphere.name}"

    # A dash in a title reads as a second kind of separator next to the bullets
    # the standard already uses, and eats more room in a tab than "•" does.
    def test_no_title_separates_its_parts_with_a_dash(self):
        offenders = [
            f"{path.name}: {title}"
            for path in TEMPLATES.rglob("*.html")
            for title in TITLE_BLOCK.findall(path.read_text())
            if "—" in title or " - " in title
        ]

        assert offenders == []


class TestLinkPreviewTitle:
    def test_matches_the_document_title(self, client, sphere):
        event = EventFactory(sphere=sphere, name="Kapitularz")

        response = _get_ok(
            client,
            reverse("web:chronology:event", kwargs={"slug": event.slug}),
            ["chronology/event.html"],
        )

        assert _titles(response) == [f"Kapitularz • {sphere.name}"] * 3

    def test_matches_the_document_title_in_the_panel(self, manager_client, event):
        response = _get_ok(
            manager_client,
            reverse("panel:proposals", kwargs={"slug": event.slug}),
            "panel/proposals.html",
        )

        assert _titles(response) == [f"Proposals • {event.name}"] * 3


class TestMetaDescription:
    def test_brand_domain_pitches_the_product(self, client):
        response = _get_ok(client, reverse("web:events"), ["index.html"])

        assert _descriptions(response) == [PRODUCT_PITCH] * 3

    def test_landing_page_pitches_the_programme_flow(self, client):
        response = _get_ok(client, reverse("web:index"), ["landing_page.html"])

        assert _descriptions(response) == [LANDING_PITCH] * 3

    def test_sphere_subdomain_names_the_sphere_instead(self, client, non_root_sphere):
        response = _get_ok(
            client,
            reverse("web:events"),
            ["index.html"],
            HTTP_HOST=non_root_sphere.site.domain,
        )

        descriptions = _descriptions(response)
        assert descriptions[0] == f"Programme and sign-ups for {non_root_sphere.name}."
        assert descriptions == [descriptions[0]] * 3

    def test_event_page_describes_the_event(self, client, sphere):
        event = EventFactory(sphere=sphere, description="Konwent gier w Krakowie")

        response = _get_ok(
            client,
            reverse("web:chronology:event", kwargs={"slug": event.slug}),
            ["chronology/event.html"],
        )

        assert _descriptions(response) == ["Konwent gier w Krakowie"] * 3

    def test_encounter_page_describes_the_encounter(self, client, sphere):
        encounter = EncounterFactory(
            sphere=sphere, place="Kraków", description="# Kolacja i **planszówki**"
        )

        response = _get_ok(
            client,
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
            "notice_board/detail.html",
        )

        description = _meta(response, "name", "description")
        assert "Kraków" in description
        assert description.endswith("| Kolacja i planszówki")
        assert _descriptions(response) == [description] * 3

    def test_event_without_a_description_falls_back_to_the_default(
        self, client, sphere
    ):
        event = EventFactory(sphere=sphere, description="")

        response = _get_ok(
            client,
            reverse("web:chronology:event", kwargs={"slug": event.slug}),
            ["chronology/event.html"],
        )

        assert _descriptions(response) == [PRODUCT_PITCH] * 3

    def test_encounter_description_keeps_ampersands_readable(self, client, sphere):
        encounter = EncounterFactory(
            sphere=sphere, place="", description="Dungeons & Dragons"
        )

        response = _get_ok(
            client,
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
            "notice_board/detail.html",
        )

        assert _meta_raw(response, "name", "description").endswith(
            "| Dungeons &amp; Dragons"
        )

    def test_encounter_without_place_or_description_still_has_the_date(
        self, client, sphere
    ):
        encounter = EncounterFactory(sphere=sphere, place="", description="")

        response = _get_ok(
            client,
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
            "notice_board/detail.html",
        )

        description = _meta(response, "name", "description")
        assert "—" not in description
        assert "|" not in description
        assert str(encounter.start_time.year) in description


class TestMetaImage:
    def test_defaults_to_the_absolute_brand_url(self, client):
        response = _get_ok(client, reverse("web:events"), ["index.html"])

        assert (
            _meta_raw(response, "property", "og:image")
            == "http://testserver/static/logo.png"
        )

    def test_event_cover_wins_over_the_brand_image(self, client, sphere):
        event = EventFactory(sphere=sphere)
        event.cover_image = SimpleUploadedFile("cover.png", PNG_BYTES, "image/png")
        event.save()

        response = _get_ok(
            client,
            reverse("web:chronology:event", kwargs={"slug": event.slug}),
            ["chronology/event.html"],
        )

        assert _meta(response, "property", "og:image").endswith(event.cover_image.url)
