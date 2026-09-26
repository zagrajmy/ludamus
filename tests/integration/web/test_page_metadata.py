import re
from datetime import datetime, timedelta
from pathlib import Path

from django.urls import reverse
from django.utils.timezone import get_current_timezone

import ludamus
from ludamus.links.db.django.models import Track
from tests.integration.conftest import (
    AgendaItemFactory,
    EncounterFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import assert_rendered

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
    assert_rendered(response=response, template_name=template_name)
    return response


class TestPageTitle:
    def test_landing_page_titles_the_product(self, client, sphere):
        response = _get_ok(client, reverse("web:index"), ["landing_page.html"])

        assert _title(response) == LANDING_TITLE

    def test_sub_sphere_title_ends_with_the_brand(
        self, client, sphere, non_root_sphere
    ):
        response = _get_ok(
            client,
            reverse("web:index"),
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
    def test_landing_page_pitches_the_programme_flow(self, client):
        response = _get_ok(client, reverse("web:index"), ["landing_page.html"])

        assert _descriptions(response) == [LANDING_PITCH] * 3

    def test_sphere_subdomain_names_the_sphere_instead(self, client, non_root_sphere):
        response = _get_ok(
            client,
            reverse("web:index"),
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


class TestSessionLinkPreview:
    def _share(self, client, event, session_param):
        return _get_ok(
            client,
            f'{reverse("web:chronology:event", kwargs={"slug": event.slug})}'
            f"?session={session_param}",
            ["chronology/event.html"],
        )

    def _scheduled(self, event, **session_fields):
        start = datetime(2031, 5, 17, 14, 0, tzinfo=get_current_timezone())
        return AgendaItemFactory(
            session=SessionFactory(
                event=event,
                category=None,
                **({"presenter": None, "facilitator_name": ""} | session_fields),
            ),
            space=SpaceFactory(event=event, name="Sala Lustrzana"),
            start_time=start,
            end_time=start + timedelta(hours=2, minutes=30),
        ).session

    def test_names_the_session_and_its_sphere(self, client, sphere):
        event = EventFactory(sphere=sphere, name="Kapitularz")
        session = self._scheduled(event, title="Zew Cthulhu")

        response = self._share(client, event, session.pk)

        assert _titles(response) == [
            f"Kapitularz • {sphere.name}",
            f"Zew Cthulhu • {sphere.name}",
            f"Zew Cthulhu • {sphere.name}",
        ]

    def test_sub_sphere_session_ends_with_the_brand(self, client, non_root_sphere):
        event = EventFactory(sphere=non_root_sphere, name="Kapitularz")
        session = self._scheduled(event, title="Zew Cthulhu")

        response = _get_ok(
            client,
            f'{reverse("web:chronology:event", kwargs={"slug": event.slug})}'
            f"?session={session.pk}",
            ["chronology/event.html"],
            HTTP_HOST=non_root_sphere.site.domain,
        )

        assert (
            _titles(response)[1:]
            == [f"Zew Cthulhu • {non_root_sphere.name} • Zagrajmy"] * 2
        )

    def test_describes_when_where_and_what(self, client, sphere):
        event = EventFactory(sphere=sphere, description="Konwent gier")
        session = self._scheduled(
            event, description="Śledztwo w **Arkham** & okolicach."
        )

        response = self._share(client, event, session.pk)

        expected = (
            "Saturday, 17 May · 14:00–16:30 · Sala Lustrzana"
            " | Śledztwo w Arkham &amp; okolicach."
        )
        assert _descriptions(response) == [expected] * 3

    def test_session_without_a_description_stops_at_the_room(self, client, sphere):
        event = EventFactory(sphere=sphere)
        session = self._scheduled(event, description="")

        response = self._share(client, event, session.pk)

        assert (
            _descriptions(response)
            == ["Saturday, 17 May · 14:00–16:30 · Sala Lustrzana"] * 3
        )

    def test_names_the_facilitator_after_the_room(self, client, sphere):
        event = EventFactory(sphere=sphere)
        session = self._scheduled(
            event,
            presenter=UserFactory(name="Anna Nowak"),
            facilitator_name="Anna Nowak",
            description="Śledztwo.",
        )

        response = self._share(client, event, session.pk)

        expected = (
            "Saturday, 17 May · 14:00–16:30 · Sala Lustrzana · Anna Nowak | Śledztwo."
        )
        assert _descriptions(response) == [expected] * 3

    def test_names_a_facilitator_without_an_account(self, client, sphere):
        event = EventFactory(sphere=sphere)
        session = self._scheduled(
            event, facilitator_name="Jan Kowalski", description=""
        )

        response = self._share(client, event, session.pk)

        assert _meta(response, "property", "og:description").endswith(
            "· Sala Lustrzana · Jan Kowalski"
        )

    def test_shows_the_session_cover_over_the_event_cover(self, client, sphere):
        event = EventFactory(sphere=sphere, cover_image="events/hall.png")
        session = self._scheduled(event, cover_image="sessions/cthulhu.png")

        response = self._share(client, event, session.pk)

        assert _meta(response, "property", "og:image").endswith("/sessions/cthulhu.png")
        assert _meta(response, "name", "twitter:image").endswith(
            "/sessions/cthulhu.png"
        )

    def test_session_without_a_cover_shows_the_event_cover(self, client, sphere):
        event = EventFactory(sphere=sphere, cover_image="events/hall.png")
        session = self._scheduled(event)

        response = self._share(client, event, session.pk)

        assert _meta(response, "property", "og:image").endswith("/events/hall.png")

    def test_session_hidden_by_a_private_track_keeps_the_event_preview(
        self, client, sphere
    ):
        event = EventFactory(sphere=sphere, name="Kapitularz", description="Konwent")
        session = self._scheduled(event, title="Tajne spotkanie")
        session.tracks.add(
            Track.objects.create(
                event=event, name="Backstage", slug="backstage", is_public=False
            )
        )

        response = self._share(client, event, session.pk)

        assert _titles(response) == [f"Kapitularz • {sphere.name}"] * 3
        assert _descriptions(response) == ["Konwent"] * 3

    def test_session_of_another_event_keeps_the_event_preview(self, client, sphere):
        event = EventFactory(sphere=sphere, name="Kapitularz", description="Konwent")
        foreign = self._scheduled(EventFactory(sphere=sphere), title="Obcy punkt")

        response = self._share(client, event, foreign.pk)

        assert _titles(response) == [f"Kapitularz • {sphere.name}"] * 3
        assert _descriptions(response) == ["Konwent"] * 3

    def test_malformed_session_param_keeps_the_event_preview(self, client, sphere):
        event = EventFactory(sphere=sphere, name="Kapitularz", description="Konwent")

        response = self._share(client, event, "abc")

        assert _titles(response) == [f"Kapitularz • {sphere.name}"] * 3
