from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse
from django.utils import timezone

from ludamus.adapters.db.django.models import Space, Track
from ludamus.pacts.venues import PrintScopeOptionDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_response, assert_response_404


def _scope(space, name=None):
    return PrintScopeOptionDTO(pk=space.pk, name=name or space.name)


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
    selected_scope="",
    selected_track=None,
    range_hours=6,
    material="timetable",
    session_list_available=False,
    tracks_available=False,
    print_scopes=None,
):
    if print_scopes is None:
        print_scopes = []
    ctx = response.context_data
    assert isinstance(ctx["qr_svg"], str)
    assert "<svg" in ctx["qr_svg"]
    assert isinstance(ctx["range_start_value"], str)
    assert ctx["range_start_value"]
    if selected_track is None:
        selected_track = ctx["selected_track"]
    expected_options = ["timetable", "timetable-descriptions"]
    # The track scope is only offered when the event actually has tracks.
    if tracks_available:
        expected_options.append("track-timetable")
    if session_list_available:
        expected_options.append("session-list")
    assert [option.value for option in ctx["material_options"]] == expected_options
    show_scope_control = material in {"timetable", "timetable-descriptions"}
    show_track_control = material == "track-timetable"
    show_range_controls = material == "timetable-descriptions"
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
            "print_scopes": print_scopes,
            "tracks": ANY,
            "material_options": ctx["material_options"],
            "material": material,
            "show_scope_control": show_scope_control,
            "show_track_control": show_track_control,
            "show_range_controls": show_range_controls,
            "selected_scope": selected_scope,
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

        _assert_print_ok(response, print_scopes=[_scope(space)])
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

        response = client.get(
            self._url(event.slug), {"material": "timetable-descriptions"}
        )

        _assert_print_ok(
            response, material="timetable-descriptions", print_scopes=[_scope(space)]
        )
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

        _assert_print_ok(response, print_scopes=[_scope(space)])
        assert session.title not in response.content.decode()

    def test_full_schedule_label_shown_when_a_session_is_pending(
        self, client, event, session, space, active_user
    ):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )
        pending = SessionFactory(
            presenter=active_user, event=event, participants_limit=10
        )
        AgendaItemFactory(
            session=pending,
            space=SpaceFactory(event=space.event, name="Side Room"),
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

        _assert_print_ok(response, print_scopes=[_scope(space)])
        assert session.title in response.content.decode()

    def test_scoped_to_node_shows_logo_capacity_and_scope_name(
        self, client, event, session, space
    ):
        event.logo = "events/logo.png"
        event.save()
        parent = Space.objects.create(event=event, name="Hall", slug="hall")
        space.parent = parent
        space.capacity = 30
        space.save()
        _confirmed_item(event, session, space)

        response = client.get(f"{self._url(event.slug)}?scope={parent.pk}")

        _assert_print_ok(
            response,
            logo="events/logo.png",
            selected_scope=str(parent.pk),
            print_scopes=[
                _scope(parent, "Hall"),
                _scope(space, f"Hall > {space.name}"),
            ],
        )
        content = response.content.decode()
        assert "events/logo.png" in content
        assert "Hall" in content
        assert "Full schedule" in content
        assert "30" in content

    def test_falls_back_to_sphere_logo_when_event_has_none(
        self, client, event, session, space, sphere
    ):
        sphere.logo = "spheres/brand.png"
        sphere.save()
        _confirmed_item(event, session, space)

        response = client.get(self._url(event.slug))

        _assert_print_ok(
            response, logo="spheres/brand.png", print_scopes=[_scope(space)]
        )
        assert "spheres/brand.png" in response.content.decode()

    def test_invalid_range_params_fall_back_to_defaults(
        self, client, event, session, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(
            f"{self._url(event.slug)}?hours=nope&start=2026-13-40T99:99"
        )

        _assert_print_ok(response, print_scopes=[_scope(space)])

    def test_explicit_start_and_hours_are_applied(self, client, event, session, space):
        _confirmed_item(event, session, space)
        start = event.start_time.strftime("%Y-%m-%dT%H:%M")
        hours = 3

        response = client.get(f"{self._url(event.slug)}?start={start}&hours={hours}")

        _assert_print_ok(response, range_hours=hours, print_scopes=[_scope(space)])

    def test_unknown_scope_is_not_found(self, client, event):
        response = client.get(f"{self._url(event.slug)}?scope=987654")

        assert_response_404(response)

    def test_non_integer_scope_falls_back_to_full_event(
        self, client, event, session, space
    ):
        # A non-numeric scope param can't name a node, so it's ignored and the
        # whole event renders.
        _confirmed_item(event, session, space)

        response = client.get(f"{self._url(event.slug)}?scope=not-a-number")

        _assert_print_ok(response, print_scopes=[_scope(space)])

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

        _assert_print_ok(
            response,
            material="session-list",
            session_list_available=True,
            tracks_available=True,
            print_scopes=[_scope(space)],
        )
        content = response.content.decode()
        assert '<option value="session-list"' in content
        assert session.title in content
        assert session.description in content

    def test_stale_track_slug_falls_back_to_first_track(
        self, client, event, session, space
    ):
        track = Track.objects.create(
            event=event, name="Focused Track", slug="focused-track", is_public=True
        )
        session.tracks.add(track)
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(
            self._url(event.slug), {"material": "track-timetable", "track": "stale"}
        )

        # A stale slug must not silently widen to the whole event; it resolves
        # to the first available track instead.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/print.html",
            context_data=ANY,
        )
        assert response.context_data["selected_track"] == "focused-track"

    def test_timetable_scoped_to_a_single_room(self, client, event, session, space):
        # A single room is now a scope like any other node (no separate "space"
        # material): pick the leaf in the scope picker.
        _confirmed_item(event, session, space)

        response = client.get(f"{self._url(event.slug)}?scope={space.pk}")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/print.html",
            context_data=ANY,
        )
        assert response.context_data["material"] == "timetable"
        assert response.context_data["selected_scope"] == str(space.pk)
        assert session.title in response.content.decode()

    def test_track_timetable_scoped_to_selected_track(
        self, client, event, session, space
    ):
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )
        session.tracks.add(track)
        space.tracks.add(track)
        _confirmed_item(event, session, space)

        response = client.get(
            self._url(event.slug), {"material": "track-timetable", "track": track.slug}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/print.html",
            context_data=ANY,
        )
        assert response.context_data["material"] == "track-timetable"
        assert response.context_data["selected_track"] == "main-track"
        assert session.title in response.content.decode()


class TestEventPagePrintHijack:
    def test_event_page_points_to_print_page(self, client, event):
        url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        print_url = reverse("web:chronology:event-print", kwargs={"slug": event.slug})

        content = client.get(url).content.decode()

        assert "data-event-print" in content
        assert print_url in content
