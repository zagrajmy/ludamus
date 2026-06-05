from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse
from django.utils import timezone

from ludamus.adapters.db.django.models import Track
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_response, assert_response_404


def _confirmed_item(event, session, space):
    return AgendaItemFactory(
        session=session,
        space=space,
        session_confirmed=True,
        start_time=event.start_time,
        end_time=event.start_time + timedelta(hours=1),
    )


def _assert_print_ok(
    response,
    *,
    logo="",
    selected_venue="",
    selected_area="",
    selected_space=None,
    selected_track=None,
    range_hours=6,
    material="event-timetable",
    session_list_available=False,
):
    ctx = response.context_data
    assert isinstance(ctx["qr_svg"], str)
    assert "<svg" in ctx["qr_svg"]
    assert isinstance(ctx["range_start_value"], str)
    assert ctx["range_start_value"]
    if selected_space is None:
        selected_space = ctx["selected_space"]
    if selected_track is None:
        selected_track = ctx["selected_track"]
    assert_response(
        response,
        HTTPStatus.OK,
        template_name="chronology/print.html",
        context_data={
            "event": ANY,
            "logo": logo,
            "timetable": ANY,
            "area_schedule": ANY,
            "session_list": ANY,
            "qr_svg": ctx["qr_svg"],
            "venues": ANY,
            "spaces": ANY,
            "tracks": ANY,
            "session_list_available": session_list_available,
            "material": material,
            "selected_venue": selected_venue,
            "selected_area": selected_area,
            "selected_space": selected_space,
            "selected_track": selected_track,
            "range_start_value": ctx["range_start_value"],
            "range_hours": range_hours,
        },
    )


class TestPublicEventPrintView:
    URL_NAME = "web:chronology:event-print"

    def _url(self, slug):
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_ok_renders_confirmed_session(self, client, event, session, space):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        _assert_print_ok(response)
        content = response.content.decode()
        assert session.title in content
        assert "Table of contents" in content
        assert 'href="#timetable-day-1"' in content
        assert 'id="timetable-day-1"' in content
        assert "Timetable" in content

    def test_area_descriptions_render_full_description(
        self, client, event, session, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(self._url(event.slug), {"material": "area-descriptions"})

        _assert_print_ok(response, material="area-descriptions")
        content = response.content.decode()
        assert session.title in content
        assert session.description in content
        assert 'id="area-space-1"' in content

    def test_unconfirmed_session_is_hidden(self, client, event, session, space):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=False,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        _assert_print_ok(response)
        assert session.title not in response.content.decode()

    def test_full_schedule_label_shown_when_a_session_is_pending(
        self, client, event, session, space, sphere, active_user
    ):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )
        pending = SessionFactory(
            presenter=active_user, sphere=sphere, participants_limit=10
        )
        AgendaItemFactory(
            session=pending,
            space=SpaceFactory(area=space.area, name="Side Room"),
            session_confirmed=False,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        assert "Full schedule" in response.content.decode()

    def test_full_schedule_label_hidden_when_complete(
        self, client, event, session, space
    ):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        assert "Full schedule" not in response.content.decode()

    def test_unpublished_event_is_not_found_for_anonymous(self, client, event):
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()

        response = client.get(self._url(event.slug))

        assert_response_404(response)

    def test_missing_event_is_not_found(self, client):
        response = client.get(self._url("does-not-exist"))

        assert_response_404(response)

    def test_manager_previews_unpublished_event(
        self, authenticated_client, active_user, sphere, event, session, space
    ):
        sphere.managers.add(active_user)
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()
        _confirmed_item(event, session, space)

        response = authenticated_client.get(self._url(event.slug))

        _assert_print_ok(response)
        assert session.title in response.content.decode()

    def test_scoped_to_venue_shows_logo_capacity_and_scope_name(
        self, client, event, session, venue, space
    ):
        event.logo = "events/logo.png"
        event.save()
        space.capacity = 30
        space.save()
        _confirmed_item(event, session, space)

        response = client.get(f"{self._url(event.slug)}?venue={venue.slug}")

        _assert_print_ok(
            response,
            logo="events/logo.png",
            selected_venue=venue.slug,
            material="venue-timetable",
        )
        content = response.content.decode()
        assert "events/logo.png" in content
        assert venue.name in content
        assert "Full schedule" in content
        assert "30" in content

    def test_falls_back_to_sphere_logo_when_event_has_none(
        self, client, event, session, space, sphere
    ):
        sphere.logo = "spheres/brand.png"
        sphere.save()
        _confirmed_item(event, session, space)

        response = client.get(self._url(event.slug))

        _assert_print_ok(response, logo="spheres/brand.png")
        assert "spheres/brand.png" in response.content.decode()

    def test_scoped_to_area_resolves_area_scope(
        self, client, event, session, venue, area, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(
            f"{self._url(event.slug)}?venue={venue.slug}&area={area.slug}"
        )

        _assert_print_ok(
            response,
            selected_venue=venue.slug,
            selected_area=area.slug,
            material="area-timetable",
        )
        assert area.name in response.content.decode()

    def test_invalid_range_params_fall_back_to_defaults(
        self, client, event, session, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(
            f"{self._url(event.slug)}?hours=nope&start=2026-13-40T99:99"
        )

        _assert_print_ok(response)

    def test_explicit_start_and_hours_are_applied(self, client, event, session, space):
        _confirmed_item(event, session, space)
        start = event.start_time.strftime("%Y-%m-%dT%H:%M")
        hours = 3

        response = client.get(f"{self._url(event.slug)}?start={start}&hours={hours}")

        _assert_print_ok(response, range_hours=hours)

    def test_unknown_venue_is_not_found(self, client, event):
        response = client.get(f"{self._url(event.slug)}?venue=does-not-exist")

        assert_response_404(response)

    def test_event_without_venues_renders_empty_states(self, client, sphere):
        bare = EventFactory(sphere=sphere, slug="bare-event")

        response = client.get(self._url(bare.slug))

        _assert_print_ok(response)

    def test_session_list_material_falls_back_when_event_is_not_eligible(
        self, client, event
    ):
        response = client.get(self._url(event.slug), {"material": "session-list"})

        _assert_print_ok(response)
        assert b'value="session-list"' not in response.content

    def test_session_list_renders_for_single_track_single_timeslot(
        self, client, event, session, space
    ):
        track = Track.objects.create(
            event=event, name="Focused Track", slug="focused-track", is_public=True
        )
        session.tracks.add(track)
        TimeSlotFactory(
            event=event,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=2),
        )
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug), {"material": "session-list"})

        _assert_print_ok(response, material="session-list", session_list_available=True)
        content = response.content.decode()
        assert '<option value="session-list"' in content
        assert session.title in content
        assert session.description in content


class TestEventPagePrintHijack:
    def test_event_page_points_to_print_page(self, client, event):
        url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        print_url = reverse("web:chronology:event-print", kwargs={"slug": event.slug})

        content = client.get(url).content.decode()

        assert "data-event-print" in content
        assert print_url in content
