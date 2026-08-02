from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import localdate

from ludamus.gates.web.django.event.print import MATERIAL_SPECS_BY_VALUE
from ludamus.links.db.django.models import Space, Track
from ludamus.pacts import EventDTO
from ludamus.pacts.printing import (
    DoorCardDTO,
    DoorCardEntryDTO,
    DoorCardsDocumentDTO,
    PrintOptionDTO,
    PrintSessionDTO,
    PrintTimetableCellDTO,
    PrintTimetableDocumentDTO,
    PrintTimetablePageDTO,
    PrintTimetableRowDTO,
)
from ludamus.pacts.venues import PrintScopeOptionDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import (
    assert_cache_control,
    assert_response,
    assert_response_404,
)


def _specs(*values):
    return tuple(MATERIAL_SPECS_BY_VALUE[value] for value in values)


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
    range_hours=None,
    material="timetable",
    descriptions=False,
    unconfirmed=False,
    session_list_available=False,
    tracks_available=False,
    panel_access=False,
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
    expected_options = ["timetable"]
    # The track scope is only offered when the event actually has tracks.
    if tracks_available:
        expected_options.append("track-timetable")
    if session_list_available:
        expected_options.append("session-list")
    expected_options.append("door-cards")
    assert [option.value for option in ctx["material_options"]] == expected_options
    show_scope_control = material in {"timetable", "door-cards"}
    show_track_control = material == "track-timetable"
    show_descriptions_control = material in {
        "timetable",
        "track-timetable",
        "door-cards",
    }
    show_range_controls = material in {"timetable", "track-timetable", "door-cards"}
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
            "door_cards": ANY,
            "qr_svg": ctx["qr_svg"],
            "print_scopes": print_scopes,
            "tracks": ANY,
            "material_options": ctx["material_options"],
            "material": material,
            "show_scope_control": show_scope_control,
            "show_track_control": show_track_control,
            "show_descriptions_control": show_descriptions_control,
            "show_range_controls": show_range_controls,
            "show_unconfirmed_control": panel_access,
            "descriptions": descriptions,
            "unconfirmed": unconfirmed,
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
        assert_cache_control(response, {"public", "max-age=300"})
        # The same URL serves a manager variant; only Vary: Cookie keeps a
        # shared cache from handing it to the wrong audience.
        assert "Cookie" in response.headers.get("Vary", "")
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
            self._url(event.slug), {"material": "timetable", "descriptions": "1"}
        )

        _assert_print_ok(response, descriptions=True, print_scopes=[_scope(space)])
        content = response.content.decode()
        assert session.title in content
        assert session.description in content
        assert 'id="area-space-1"' in content

    def test_track_descriptions_list_is_scoped_to_the_selected_track(
        self, client, event, session, space, active_user
    ):
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )
        session.tracks.add(track)
        space.tracks.add(track)
        _confirmed_item(event, session, space)
        untracked_space = SpaceFactory(event=event, name="Untracked Room")
        untracked = SessionFactory(
            presenter=active_user, event=event, participants_limit=10
        )
        AgendaItemFactory(
            session=untracked,
            space=untracked_space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(
            self._url(event.slug),
            {"material": "track-timetable", "track": track.slug, "descriptions": "1"},
        )

        _assert_print_ok(
            response,
            material="track-timetable",
            descriptions=True,
            tracks_available=True,
            print_scopes=list(response.context_data["print_scopes"]),
        )
        schedule = response.context_data["area_schedule"]
        assert schedule.scope_name == track.name
        assert [s.space_name for s in schedule.spaces] == [space.name]
        assert [x.title for s in schedule.spaces for x in s.sessions] == [session.title]

    def test_legacy_descriptions_material_maps_to_the_checkbox(
        self, client, event, session, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(
            self._url(event.slug), {"material": "timetable-descriptions"}
        )

        _assert_print_ok(response, descriptions=True, print_scopes=[_scope(space)])
        assert response.context_data["area_schedule"] is not None
        assert response.context_data["timetable"] is None

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

    @pytest.mark.usefixtures("panel_access_user")
    def test_manager_and_superuser_preview_unpublished_event(
        self, authenticated_client, event, session, space
    ):
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()
        _confirmed_item(event, session, space)

        response = authenticated_client.get(self._url(event.slug))

        _assert_print_ok(response, panel_access=True, print_scopes=[_scope(space)])
        assert_cache_control(response, {"private", "max-age=5"})

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
            logo="/media/events/logo.png",
            selected_scope=str(parent.pk),
            print_scopes=[
                _scope(parent, "Hall"),
                _scope(space, f"Hall > {space.name}"),
            ],
        )
        content = response.content.decode()
        assert 'src="/media/events/logo.png"' in content
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
            response, logo="/media/spheres/brand.png", print_scopes=[_scope(space)]
        )
        assert 'src="/media/spheres/brand.png"' in response.content.decode()

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

    def test_explicit_range_clips_the_timetable_grid(
        self, client, event, session, space, active_user
    ):
        _confirmed_item(event, session, space)
        late = SessionFactory(presenter=active_user, event=event, participants_limit=10)
        AgendaItemFactory(
            session=late,
            space=space,
            session_confirmed=True,
            start_time=event.start_time + timedelta(hours=10),
            end_time=event.start_time + timedelta(hours=11),
        )
        start = event.start_time.strftime("%Y-%m-%dT%H:%M")

        response = client.get(f"{self._url(event.slug)}?start={start}&hours=3")

        _assert_print_ok(response, range_hours=3, print_scopes=[_scope(space)])
        titles = [
            s.title
            for page in response.context_data["timetable"].pages
            for row in page.rows
            for cell in row.cells
            for s in cell.sessions
        ]
        assert titles == [session.title]

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
            context_data={
                "area_schedule": None,
                "door_cards": None,
                "event": EventDTO.model_validate(event),
                "logo": "",
                "descriptions": False,
                "unconfirmed": False,
                "material": "track-timetable",
                "material_options": _specs(
                    "timetable", "track-timetable", "door-cards"
                ),
                "print_scopes": [_scope(space)],
                "qr_svg": response.context_data["qr_svg"],
                "range_hours": None,
                "range_start_value": response.context_data["range_start_value"],
                "selected_scope": "",
                "selected_track": "focused-track",
                "session_list": None,
                "show_scope_control": False,
                "show_descriptions_control": True,
                "show_range_controls": True,
                "show_unconfirmed_control": False,
                "show_track_control": True,
                "timetable": PrintTimetableDocumentDTO(
                    event_name=event.name,
                    event_description=event.description,
                    event_start=event.start_time,
                    event_end=event.end_time,
                    scope_name=track.name,
                    is_complete=False,
                    pages=[],
                ),
                "tracks": [
                    PrintOptionDTO(pk=track.pk, name=track.name, slug=track.slug)
                ],
            },
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
            context_data={
                "area_schedule": None,
                "door_cards": None,
                "event": EventDTO.model_validate(event),
                "logo": "",
                "descriptions": False,
                "unconfirmed": False,
                "material": "timetable",
                "material_options": _specs("timetable", "door-cards"),
                "print_scopes": [_scope(space)],
                "qr_svg": response.context_data["qr_svg"],
                "range_hours": None,
                "range_start_value": response.context_data["range_start_value"],
                "selected_scope": str(space.pk),
                "selected_track": "",
                "session_list": None,
                "show_scope_control": True,
                "show_descriptions_control": True,
                "show_range_controls": True,
                "show_unconfirmed_control": False,
                "show_track_control": False,
                "timetable": PrintTimetableDocumentDTO(
                    event_name=event.name,
                    event_description=event.description,
                    event_start=event.start_time,
                    event_end=event.end_time,
                    scope_name=space.name,
                    is_complete=False,
                    pages=[
                        PrintTimetablePageDTO(
                            day=event.start_time.date(),
                            space_names=[space.name],
                            rows=[
                                PrintTimetableRowDTO(
                                    start_time=event.start_time,
                                    end_time=event.start_time + timedelta(hours=1),
                                    cells=[
                                        PrintTimetableCellDTO(
                                            sessions=[
                                                PrintSessionDTO(
                                                    title=session.title,
                                                    presenter_name="Test User",
                                                )
                                            ]
                                        )
                                    ],
                                )
                            ],
                            space_range_name=None,
                        )
                    ],
                ),
                "tracks": [],
            },
        )
        assert response.context_data["material"] == "timetable"
        assert response.context_data["selected_scope"] == str(space.pk)

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
            context_data={
                "area_schedule": None,
                "door_cards": None,
                "event": EventDTO.model_validate(event),
                "logo": "",
                "descriptions": False,
                "unconfirmed": False,
                "material": "track-timetable",
                "material_options": _specs(
                    "timetable", "track-timetable", "door-cards"
                ),
                "print_scopes": [_scope(space)],
                "qr_svg": response.context_data["qr_svg"],
                "range_hours": None,
                "range_start_value": response.context_data["range_start_value"],
                "selected_scope": "",
                "selected_track": "main-track",
                "session_list": None,
                "show_scope_control": False,
                "show_descriptions_control": True,
                "show_range_controls": True,
                "show_unconfirmed_control": False,
                "show_track_control": True,
                "timetable": PrintTimetableDocumentDTO(
                    event_name=event.name,
                    event_description=event.description,
                    event_start=event.start_time,
                    event_end=event.end_time,
                    scope_name=track.name,
                    is_complete=False,
                    pages=[
                        PrintTimetablePageDTO(
                            day=event.start_time.date(),
                            space_names=[space.name],
                            rows=[
                                PrintTimetableRowDTO(
                                    start_time=event.start_time,
                                    end_time=event.start_time + timedelta(hours=1),
                                    cells=[
                                        PrintTimetableCellDTO(
                                            sessions=[
                                                PrintSessionDTO(
                                                    title=session.title,
                                                    presenter_name="Test User",
                                                )
                                            ]
                                        )
                                    ],
                                )
                            ],
                            space_range_name=None,
                        )
                    ],
                ),
                "tracks": [
                    PrintOptionDTO(pk=track.pk, name=track.name, slug=track.slug)
                ],
            },
        )
        assert response.context_data["material"] == "track-timetable"
        assert response.context_data["selected_track"] == "main-track"

    def test_door_cards_material_renders_one_card_per_room_and_day(
        self, client, event, session, space
    ):
        # Participant-facing cards: a room with nothing scheduled gets no card.
        empty_hall = SpaceFactory(event=event, name="Empty Hall")
        _confirmed_item(event, session, space)

        response = client.get(self._url(event.slug), {"material": "door-cards"})

        # Both rooms are root leaves, listed in (order, name) order.
        expected_scopes = sorted(
            [_scope(space), _scope(empty_hall)], key=lambda scope: scope.name
        )
        _assert_print_ok(response, material="door-cards", print_scopes=expected_scopes)
        assert response.context_data["timetable"] is None
        assert response.context_data["door_cards"] == DoorCardsDocumentDTO(
            event_name=event.name,
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            scope_name=None,
            cards=[
                DoorCardDTO(
                    space_name=space.name,
                    capacity=space.capacity,
                    day=localdate(event.start_time),
                    entries=[
                        DoorCardEntryDTO(
                            start_time=event.start_time,
                            end_time=event.start_time + timedelta(hours=1),
                            session=PrintSessionDTO(
                                title=session.title, presenter_name=session.display_name
                            ),
                        )
                    ],
                )
            ],
        )

    def test_door_cards_with_descriptions_swap_to_the_area_schedule(
        self, client, event, session, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(
            self._url(event.slug), {"material": "door-cards", "descriptions": "1"}
        )

        _assert_print_ok(
            response,
            material="door-cards",
            descriptions=True,
            print_scopes=[_scope(space)],
        )
        assert response.context_data["door_cards"] is None
        assert response.context_data["area_schedule"] is not None

    def test_door_cards_limited_to_time_window(self, client, event, session, space):
        _confirmed_item(event, session, space)
        later_session = SessionFactory(event=event, category=None, title="Late Larp")
        AgendaItemFactory(
            session=later_session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time + timedelta(hours=6),
            end_time=event.start_time + timedelta(hours=7),
        )
        start = event.start_time.strftime("%Y-%m-%dT%H:%M")

        response = client.get(
            self._url(event.slug),
            {"material": "door-cards", "start": start, "hours": "3"},
        )

        _assert_print_ok(
            response, material="door-cards", range_hours=3, print_scopes=[_scope(space)]
        )
        cards = response.context_data["door_cards"].cards
        assert [[e.session.title for e in card.entries] for card in cards] == [
            [session.title]
        ]

    def test_manager_can_include_unconfirmed_sessions(
        self, authenticated_client, active_user, sphere, event, session, space
    ):
        sphere.managers.add(active_user)
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=False,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(self._url(event.slug), {"unconfirmed": "1"})

        _assert_print_ok(
            response, unconfirmed=True, panel_access=True, print_scopes=[_scope(space)]
        )
        assert_cache_control(response, {"private", "max-age=5"})
        titles = [
            s.title
            for page in response.context_data["timetable"].pages
            for row in page.rows
            for cell in row.cells
            for s in cell.sessions
        ]
        assert titles == [session.title]

    def test_unconfirmed_param_is_ignored_for_participants(
        self, client, event, session, space
    ):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=False,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug), {"unconfirmed": "1"})

        _assert_print_ok(response, print_scopes=[_scope(space)])
        assert_cache_control(response, {"public", "max-age=300"})
        assert response.context_data["timetable"].pages == []

    def test_manager_visit_is_privately_cached_and_marks_printed(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        assert event.printables_last_printed_at is None

        response = authenticated_client.get(self._url(event.slug))

        _assert_print_ok(response, panel_access=True)
        assert_cache_control(response, {"private", "max-age=5"})
        assert "Cookie" in response.headers.get("Vary", "")
        event.refresh_from_db()
        assert event.printables_last_printed_at is not None

    def test_participant_visit_does_not_mark_printed(self, client, event):
        response = client.get(self._url(event.slug))

        _assert_print_ok(response)
        event.refresh_from_db()
        assert event.printables_last_printed_at is None


class TestEventPagePrintHijack:
    def test_event_page_points_to_print_page(self, client, event):
        url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        print_url = reverse("web:chronology:event-print", kwargs={"slug": event.slug})

        content = client.get(url).content.decode()

        assert "data-event-print" in content
        assert print_url in content
