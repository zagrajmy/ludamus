from datetime import timedelta

from django.urls import reverse
from django.utils.timezone import localdate

from ludamus.links.db.django.models import Track
from ludamus.pacts.printing import (
    DoorCardDTO,
    DoorCardEntryDTO,
    DoorCardsDocumentDTO,
    PrintSessionDTO,
    PrintSessionListDocumentDTO,
    PrintTimetableCellDTO,
    PrintTimetableDocumentDTO,
    PrintTimetablePageDTO,
    PrintTimetableRowDTO,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_cache_control
from tests.integration.web.chronology.test_event_print_page import (
    _area_schedule_document,
    _assert_print_ok,
    _confirmed_item,
    _scope,
)


class TestPublicEventPrintMaterials:
    URL_NAME = "web:chronology:event-print"

    def _url(self, slug):
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_door_cards_material_renders_one_card_per_room_and_day(
        self, client, event, session, space
    ):
        # Participant-facing cards: a room with nothing scheduled gets no card.
        empty_hall = SpaceFactory(event=event, name="Empty Hall")
        space.capacity = 18
        space.save(update_fields=["capacity"])
        _confirmed_item(event, session, space)

        response = client.get(self._url(event.slug), {"material": "door-cards"})

        # Both rooms are root leaves, listed in (order, name) order.
        expected_scopes = sorted(
            [_scope(space), _scope(empty_hall)], key=lambda scope: scope.name
        )
        _assert_print_ok(
            response,
            material="door-cards",
            print_scopes=expected_scopes,
            timetable=None,
            door_cards=DoorCardsDocumentDTO(
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
                                    title=session.title,
                                    presenter_name=session.display_name,
                                ),
                            )
                        ],
                    )
                ],
            ),
        )

    def test_door_cards_without_scheduled_rooms_render_the_empty_sheet(
        self, client, event
    ):
        response = client.get(self._url(event.slug), {"material": "door-cards"})

        _assert_print_ok(
            response,
            material="door-cards",
            timetable=None,
            door_cards=DoorCardsDocumentDTO(
                event_name=event.name,
                event_description=event.description,
                event_start=event.start_time,
                event_end=event.end_time,
                scope_name=None,
                cards=[],
            ),
        )

    def test_unconfirmed_toggle_with_nothing_scheduled_keeps_empty_timetable(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self._url(event.slug), {"unconfirmed": "1"})

        _assert_print_ok(
            response,
            unconfirmed=True,
            panel_access=True,
            timetable=PrintTimetableDocumentDTO(
                event_name=event.name,
                event_description=event.description,
                event_start=event.start_time,
                event_end=event.end_time,
                scope_name=None,
                is_complete=False,
                pages=[],
            ),
        )

    def test_empty_session_list_renders_empty_state(self, client, event, space):
        Track.objects.create(
            event=event, name="Focused Track", slug="focused-track", is_public=True
        )
        TimeSlotFactory(
            event=event,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=2),
        )

        response = client.get(self._url(event.slug), {"material": "session-list"})

        _assert_print_ok(
            response,
            material="session-list",
            session_list_available=True,
            tracks_available=True,
            print_scopes=[_scope(space)],
            timetable=None,
            session_list=PrintSessionListDocumentDTO(
                event_name=event.name,
                event_description=event.description,
                event_start=event.start_time,
                event_end=event.end_time,
                scope_name="Focused Track",
                sessions=[],
            ),
        )

    def test_empty_session_list_with_unconfirmed_toggle(
        self, authenticated_client, active_user, sphere, event, space
    ):
        sphere.managers.add(active_user)
        Track.objects.create(
            event=event, name="Focused Track", slug="focused-track", is_public=True
        )
        TimeSlotFactory(
            event=event,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=2),
        )

        response = authenticated_client.get(
            self._url(event.slug), {"material": "session-list", "unconfirmed": "1"}
        )

        _assert_print_ok(
            response,
            material="session-list",
            unconfirmed=True,
            session_list_available=True,
            tracks_available=True,
            panel_access=True,
            print_scopes=[_scope(space)],
            timetable=None,
            session_list=PrintSessionListDocumentDTO(
                event_name=event.name,
                event_description=event.description,
                event_start=event.start_time,
                event_end=event.end_time,
                scope_name="Focused Track",
                sessions=[],
            ),
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
            timetable=None,
            area_schedule=_area_schedule_document(
                event=event, session=session, space=space
            ),
            door_cards=None,
        )

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
            response,
            material="door-cards",
            range_hours=3,
            print_scopes=[_scope(space)],
            timetable=None,
            door_cards=DoorCardsDocumentDTO(
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
                                    title=session.title,
                                    presenter_name=session.display_name,
                                ),
                            )
                        ],
                    )
                ],
            ),
        )

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
            response,
            unconfirmed=True,
            panel_access=True,
            print_scopes=[_scope(space)],
            timetable=PrintTimetableDocumentDTO(
                event_name=event.name,
                event_description=event.description,
                event_start=event.start_time,
                event_end=event.end_time,
                scope_name=None,
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
                                                presenter_name=session.display_name,
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
        )
        assert_cache_control(response, {"private", "max-age=5"})

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

        _assert_print_ok(
            response,
            print_scopes=[_scope(space)],
            timetable=PrintTimetableDocumentDTO(
                event_name=event.name,
                event_description=event.description,
                event_start=event.start_time,
                event_end=event.end_time,
                scope_name=None,
                is_complete=False,
                pages=[],
            ),
        )
        assert_cache_control(response, {"public", "max-age=300"})

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
