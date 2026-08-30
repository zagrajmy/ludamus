import json
import re
from dataclasses import replace
from datetime import UTC, timedelta
from http import HTTPStatus

import pytest
import responses
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from django.utils import timezone
from freezegun import freeze_time

from ludamus.adapters.web.django.views import EventPageView
from ludamus.gates.web.django.chronology.event_presentation import (
    ParticipationInfo,
    SessionData,
    build_display_field_row,
)
from ludamus.gates.web.django.chronology.schedule import (
    RoomLane,
    RoomLaneRow,
    RoomLanes,
    RoomLaneTile,
    ScheduleDay,
    ScheduleHour,
    ScheduleTile,
)
from ludamus.gates.web.django.entities import UserInfo
from ludamus.gates.web.django.helpers import placeholder_cover_url
from ludamus.links.db.django.models import (
    Connection,
    DomainEnrollmentConfig,
    EnrollmentConfig,
    EventIntegration,
    EventSettings,
    SessionBookmark,
    SessionField,
    SessionFieldOption,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
    Track,
    UserEnrollmentConfig,
)
from ludamus.links.db.django.repositories.chronology import location_data
from ludamus.links.encryption import FernetEncryptor
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import (
    AgendaItemDTO,
    OrganizerFieldDTO,
    OrganizerFieldOptionDTO,
    SessionDTO,
    SessionFieldValueDTO,
    VirtualEnrollmentConfig,
)
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import (
    PNG_BYTES,
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
    UserFactory,
)
from tests.integration.utils import assert_rendered, assert_response
from tests.integration.web.chronology.helpers import (
    compact_day,
    event_page_context,
    make_half_full_session,
    proposal_card,
    session_card,
)


def _schedule_tile(data: SessionData) -> ScheduleTile:
    if data.agenda_item is None:
        raise ValueError("scheduled test data needs an agenda item")
    return ScheduleTile(
        data=data,
        start=timezone.localtime(data.agenda_item.start_time),
        end=timezone.localtime(data.agenda_item.end_time),
    )


def _single_schedule_day(data: SessionData) -> ScheduleDay:
    tile = _schedule_tile(data)
    hour_start = tile.start.replace(minute=0, second=0, microsecond=0)
    return ScheduleDay(
        day_start=hour_start,
        hours=[ScheduleHour(start=hour_start, tiles=[tile])],
        tiles=[tile],
    )


def _field_dto(field):
    # What SessionFieldRepository.list_by_event hands the filter panel.
    return OrganizerFieldDTO(
        allow_custom=field.allow_custom,
        field_type=field.field_type,
        help_text=field.help_text,
        icon=field.icon,
        is_multiple=field.is_multiple,
        is_public=field.is_public,
        max_length=field.max_length,
        name=field.name,
        options=[
            OrganizerFieldOptionDTO.model_validate(option)
            # Queried, not walked off `field`: the helper runs once per
            # expected context, and the relation is unprefetched here.
            for option in SessionFieldOption.objects.filter(field=field)
        ],
        order=field.order,
        pk=field.pk,
        question=field.question,
        slug=field.slug,
    )


# Hour offsets from the event start for the proposal that names preferred
# slots: three of them, so the card shows the earliest and counts the rest.
_PREFERRED_SLOT_OFFSETS = (0, 2, 4)

# The review queue the query-count guard grows to, from one proposal.
_PROPOSALS_IN_QUEUE = 5

MEMBERSHIP_API_URL = "https://membership-test.example.com/api/v1/endpoint"


@pytest.fixture(name="ticketing_integration")
def ticketing_integration_fixture(event, settings, sphere):
    # Membership lookups only happen for an event wired to a ticketing
    # integration, so every test that expects an outbound call needs this.
    shop_connection = Connection.objects.create(
        sphere=sphere,
        display_name="Kapitularz",
        secret=FernetEncryptor(settings.CREDENTIALS_ENCRYPTION_KEY).encrypt(
            b"membership-test-token"
        ),
    )
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.TICKETING.value,
        implementation=IntegrationImplementationId.SKLEP_KAPITULARZ.value,
        connection=shop_connection,
        display_name="Kapitularz",
        config_json=json.dumps({"base_url": MEMBERSHIP_API_URL}),
    )


class TestEventPageView:
    URL_NAME = "web:chronology:event"

    def _get_url(self, slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_ok(self, client, event):
        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
            contains="Upcoming",
            not_contains="Enrollment Open",
            cache_control={"private", "max-age=180"},
        )
        assert "Cookie" in response.headers.get("Vary", "")

    def test_offered_seats_count_toward_capacity(self, client, sphere):
        event = EventFactory(sphere=sphere)
        session, seats = make_half_full_session(event)
        agenda_item = session.agenda_item

        response = client.get(self._get_url(event.slug))

        # The offered seat holds a place in the roster, so both seats are gone.
        card = session_card(
            agenda_item,
            presenter=session.presenter,
            enrolled_count=session.participants_limit,
            is_full=True,
            session_participations=[
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(seat.user), gravatar_url=gravatar_url
                    ),
                    status=seat.status,
                    creation_time=seat.creation_time,
                )
                for seat in seats
            ],
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
                total_enrolled=2,
            ),
            template_name=["chronology/event.html"],
        )

    def test_session_card_link_opens_on_current_event(self, agenda_item, client, event):
        response = client.get(self._get_url(event.slug))

        card = session_card(agenda_item, presenter=agenda_item.session.presenter)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains=f'href="?session={agenda_item.session.pk}"',
            not_contains="Missing variable session_link_base",
        )

    @pytest.mark.usefixtures("agenda_item")
    def test_ok_participants_label_toggle(self, client, event):
        response_default = client.get(self._get_url(event.slug))
        content_default = response_default.content.decode()

        event.use_participants_label = True
        event.save()
        response_toggled = client.get(self._get_url(event.slug))
        content_toggled = response_toggled.content.decode()

        assert response_default.status_code == HTTPStatus.OK
        assert response_toggled.status_code == HTTPStatus.OK
        # "Players" only appears as the header count label; "Participants" also
        # names a session-modal tab, so a bare presence check would always pass.
        # Compare its count across the toggle instead.
        assert "Players" in content_default
        assert "Players" not in content_toggled
        assert content_toggled.count("Participants") > content_default.count(
            "Participants"
        )

    def test_ok_compact_schedule_for_big_event(
        self, active_user, agenda_item, client, event, monkeypatch
    ):
        # Drop the threshold so a single scheduled session flips the page to the
        # compact list + hour scrubber instead of the card grid.
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        schedule_day = _single_schedule_day(session_data)
        url = self._get_url(event.slug)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=url,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                compact_schedule=True,
                schedule_days=[schedule_day],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains=[
                "schedule-rail",
                'data-rail-hour="',
                f"?session={agenda_item.session.pk}",
            ],
            # The compact list replaces the multi-column card grid.
            not_contains="grid-cols-1 lg:grid-cols-2 xl:grid-cols-3",
        )

    def test_ok_compact_schedule_marks_bookmarked_session(
        self, agenda_item, active_user, authenticated_client, event, monkeypatch, space
    ):
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )
        SessionBookmark.objects.create(user=active_user, session=agenda_item.session)
        # A second, un-bookmarked session renders the inactive toggle state.
        other = AgendaItemFactory(
            session=SessionFactory(event=event, category=None), space=space
        )

        response = authenticated_client.get(self._get_url(event.slug))

        cards = [
            session_card(
                agenda_item,
                presenter=active_user,
                bookmark_count=1,
                user_bookmarked=True,
                can_edit=True,
            ),
            session_card(other, presenter=other.session.presenter),
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                compact_schedule=True,
                hour_data={
                    agenda_item.start_time: [cards[0]],
                    other.start_time: [cards[1]],
                },
                schedule_days=[compact_day(cards)],
                sessions=cards,
                has_enrollable_sessions=True,
                scheduled_count=2,
            ),
            template_name=["chronology/event.html"],
            contains=[
                'data-bookmarked="true"',
                'aria-pressed="true"',
                'data-bookmarked="false"',
                'aria-pressed="false"',
            ],
        )

    def test_ok_compact_schedule_omits_not_available_label(
        self, active_user, agenda_item, client, event, monkeypatch
    ):
        # The session has no active enrollment config, so it is not available.
        # On the compact layout that must render as blank, not a repeated label.
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        schedule_day = _single_schedule_day(session_data)
        url = self._get_url(event.slug)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=url,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                compact_schedule=True,
                schedule_days=[schedule_day],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            not_contains="Not Available",
        )

    # Pinned: the ongoing session spans now±1h, so a run near local midnight
    # would split it across two dates and yield an extra schedule day. Half
    # past the local hour (12:30 Europe/Warsaw), so the ended session has a
    # non-empty window between the hour bucket's start and `now()`.
    @freeze_time("2026-06-15 10:30:00")
    def test_ok_compact_schedule_renders_all_row_variants(
        self, client, event, space, monkeypatch
    ):
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )
        now = timezone.now()
        event.publication_time = now - timedelta(days=14)
        event.start_time = now + timedelta(days=7)
        event.end_time = event.start_time + timedelta(hours=8)
        event.save()
        EnrollmentConfig.objects.create(
            event=event,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=5),
            percentage_slots=100,
        )
        # A limit_to_end_time config marks ongoing sessions as "In Progress".
        EnrollmentConfig.objects.create(
            event=event,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=5),
            percentage_slots=100,
            limit_to_end_time=True,
        )
        # Two full days out so the local-date grouping can never collide with
        # the ended/ongoing sessions, whatever the wall clock is at test time.
        day_one = (now + timedelta(days=2)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )

        def scheduled(*, start, end, **session_kwargs):
            session = SessionFactory(event=event, category=None, **session_kwargs)
            AgendaItemFactory(
                session=session, space=space, start_time=start, end_time=end
            )
            session.refresh_from_db()
            return session

        plenty = scheduled(
            start=day_one,
            end=day_one + timedelta(hours=2),
            participants_limit=10,
            min_age=16,
            duration="PT2H",
        )
        # Same slot as `plenty` — covers the append-to-existing-hour branch.
        scarce = scheduled(
            start=day_one,
            end=day_one + timedelta(hours=1),
            participants_limit=5,
            min_age=0,
        )
        for _ in range(4):
            SessionParticipation.objects.create(
                session=scarce,
                user=UserFactory(),
                status=SessionParticipationStatus.CONFIRMED,
            )
        # Second slot on the same day — covers the append-to-existing-day branch.
        no_enrollment = scheduled(
            start=day_one + timedelta(hours=3),
            end=day_one + timedelta(hours=4),
            participants_limit=0,
            min_age=0,
        )
        full = scheduled(
            start=day_one + timedelta(days=1),
            end=day_one + timedelta(days=1, hours=1),
            participants_limit=2,
            min_age=0,
        )
        for status in (
            SessionParticipationStatus.CONFIRMED,
            SessionParticipationStatus.CONFIRMED,
            SessionParticipationStatus.WAITING,
        ):
            SessionParticipation.objects.create(
                session=full, user=UserFactory(), status=status
            )
        # Both windows stay inside the current local hour, and the ongoing one
        # is cut at midnight: a session crossing local midnight gets a tile per
        # local date, which would spread the two over two schedule days.
        local_now = timezone.localtime(now)
        hour_start = local_now.replace(minute=0, second=0, microsecond=0)
        midnight = (hour_start + timedelta(days=1)).replace(hour=0)
        ended = scheduled(
            start=hour_start, end=local_now, participants_limit=4, min_age=0
        )
        ongoing = scheduled(
            start=local_now,
            end=min(local_now + timedelta(hours=1), midnight),
            participants_limit=4,
            min_age=0,
        )
        game_type = SessionField.objects.create(
            event=event,
            name="Game Type",
            question="Game Type",
            slug="game-type",
            field_type="select",
            is_multiple=True,
            is_public=True,
            icon="puzzle-piece",
        )
        SessionFieldValue.objects.create(session=plenty, field=game_type, value=["RPG"])
        event_settings, _ = EventSettings.objects.get_or_create(event=event)
        event_settings.displayed_session_fields.add(game_type)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="puzzle-piece",
            field_id=game_type.pk,
            field_name="Game Type",
            field_question="Game Type",
            field_slug="game-type",
            field_type="select",
            is_public=True,
            value=["RPG"],
        )
        base_cards = {
            ended.pk: session_card(
                ended.agenda_item,
                presenter=ended.presenter,
                is_enrollment_available=True,
                # An ended session is also "ongoing" until its window closes;
                # both flags feed the inactive row treatment.
                is_ended=True,
                is_ongoing=True,
                should_show_as_inactive=True,
            ),
            ongoing.pk: session_card(
                ongoing.agenda_item,
                presenter=ongoing.presenter,
                is_enrollment_available=True,
                is_ongoing=True,
                should_show_as_inactive=True,
            ),
            plenty.pk: session_card(
                plenty.agenda_item,
                presenter=plenty.presenter,
                is_enrollment_available=True,
                displayed_field_rows=[build_display_field_row(field_value_dto)],
                field_values=[field_value_dto],
            ),
            scarce.pk: session_card(
                scarce.agenda_item,
                presenter=scarce.presenter,
                is_enrollment_available=True,
                enrolled_count=4,
            ),
            no_enrollment.pk: session_card(
                no_enrollment.agenda_item, presenter=no_enrollment.presenter
            ),
            full.pk: session_card(
                full.agenda_item,
                presenter=full.presenter,
                is_enrollment_available=True,
                enrolled_count=2,
                is_full=True,
                waiting_count=1,
            ),
        }

        def hour_of(session):
            return timezone.localtime(session.agenda_item.start_time).replace(
                minute=0, second=0, microsecond=0
            )

        def with_participants(session):
            # Every card carries the people already seated on its session.
            return replace(
                base_cards[session.pk],
                session_participations=[
                    ParticipationInfo(
                        user=UserInfo.from_user_dto(
                            UserDTO.model_validate(participation.user),
                            gravatar_url=gravatar_url,
                        ),
                        status=participation.status,
                        creation_time=participation.creation_time,
                        is_shadowbanned=False,
                    )
                    for participation in (
                        SessionParticipation.objects.filter(session=session)
                        .select_related("user")
                        .order_by("pk")
                    )
                ],
            )

        cards = {
            session.pk: with_participants(session)
            for session in (ended, ongoing, plenty, scarce, no_enrollment, full)
        }

        def tile(session):
            return ScheduleTile(
                data=cards[session.pk],
                start=timezone.localtime(session.agenda_item.start_time),
                end=timezone.localtime(session.agenda_item.end_time),
            )

        # One day per local date, one hour bucket per distinct start hour.
        expected_days = [
            ScheduleDay(
                day_start=hour_start,
                hours=[
                    ScheduleHour(start=hour_start, tiles=[tile(ended), tile(ongoing)])
                ],
                tiles=[tile(ended), tile(ongoing)],
            ),
            ScheduleDay(
                day_start=hour_of(plenty),
                hours=[
                    ScheduleHour(
                        start=hour_of(plenty), tiles=[tile(plenty), tile(scarce)]
                    ),
                    ScheduleHour(
                        start=hour_of(no_enrollment), tiles=[tile(no_enrollment)]
                    ),
                ],
                tiles=[tile(plenty), tile(scarce), tile(no_enrollment)],
            ),
            ScheduleDay(
                day_start=hour_of(full),
                hours=[ScheduleHour(start=hour_of(full), tiles=[tile(full)])],
                tiles=[tile(full)],
            ),
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                compact_schedule=True,
                sessions=list(cards.values()),
                schedule_days=expected_days,
                # 4 seats in `scarce` plus the 2 that fill `full`.
                total_enrolled=4 + 2,
                hour_data={
                    ended.agenda_item.start_time: [cards[ended.pk]],
                    ongoing.agenda_item.start_time: [cards[ongoing.pk]],
                    plenty.agenda_item.start_time: [cards[plenty.pk], cards[scarce.pk]],
                    no_enrollment.agenda_item.start_time: [cards[no_enrollment.pk]],
                    full.agenda_item.start_time: [cards[full.pk]],
                },
                has_enrollable_sessions=True,
                scheduled_count=6,
            ),
            template_name=["chronology/event.html"],
        )
        content = response.content.decode()
        # The pills render inside their own spans; match with the tag boundary
        # so e.g. the "Enrollment Open" header pill can't satisfy a pill label.
        for label in (
            "10 spots left",
            "1 spot left",
            "Full",
            "Ended",
            "In Progress",
            "16\\+",
        ):
            assert re.search(rf">\s*{label}\s*<", content), label
        assert "1 waiting" in content
        assert "2h" in content
        # The ledger row no longer carries the enrolled count; it lives in the
        # lazy-loaded session modal's capacity chip instead.
        assert 'title="4 participants enrolled"' not in content
        assert content.count("data-schedule-day") == len(expected_days)
        modal = client.get(
            reverse(
                "web:chronology:session-modal",
                kwargs={"event_slug": event.slug, "session_id": scarce.pk},
            )
        )
        assert_rendered(
            response=modal,
            template_name="chronology/parts/session-modal.html",
            contains="4/5",
        )

    def test_ok_compact_rooms_view(
        self, active_user, authenticated_client, event, monkeypatch
    ):
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )
        start = (timezone.now() + timedelta(days=2)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        arena = SpaceFactory(event=event, name="Arena")
        stage = SpaceFactory(event=event, name="Stage")
        in_arena = SessionFactory(
            event=event, category=None, duration="PT1H", min_age=16
        )
        on_stage = SessionFactory(event=event, category=None)
        later_in_arena = SessionFactory(event=event, category=None)
        AgendaItemFactory(
            session=in_arena,
            space=arena,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )
        AgendaItemFactory(
            session=on_stage,
            space=stage,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )
        AgendaItemFactory(
            session=later_in_arena,
            space=arena,
            start_time=start + timedelta(hours=2),
            end_time=start + timedelta(hours=4),
        )

        SessionBookmark.objects.create(user=active_user, session=in_arena)

        response = authenticated_client.get(f"{self._get_url(event.slug)}?view=rooms")

        local_start = timezone.localtime(start)
        cards = {
            session.pk: session_card(
                session.agenda_item, presenter=session.presenter, **overrides
            )
            for session, overrides in (
                (in_arena, {"user_bookmarked": True, "bookmark_count": 1}),
                (on_stage, {}),
                (later_in_arena, {}),
            )
        }
        room_tiles = [
            RoomLaneTile(
                data=cards[in_arena.pk],
                start=timezone.localtime(in_arena.agenda_item.start_time),
                end=timezone.localtime(in_arena.agenda_item.end_time),
                col=1,
                row_span=1,
            ),
            RoomLaneTile(
                data=cards[on_stage.pk],
                start=timezone.localtime(on_stage.agenda_item.start_time),
                end=timezone.localtime(on_stage.agenda_item.end_time),
                col=2,
                row_span=1,
            ),
            RoomLaneTile(
                data=cards[later_in_arena.pk],
                start=timezone.localtime(later_in_arena.agenda_item.start_time),
                end=timezone.localtime(later_in_arena.agenda_item.end_time),
                col=1,
                row_span=2,
            ),
        ]
        tiles_by_row = {0: room_tiles[:2], 2: room_tiles[2:]}
        url = self._get_url(event.slug)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=url,
                compact_schedule=True,
                sessions=list(cards.values()),
                hour_data={
                    start: [cards[in_arena.pk], cards[on_stage.pk]],
                    start + timedelta(hours=2): [cards[later_in_arena.pk]],
                },
                schedule_days=[
                    ScheduleDay(
                        day_start=local_start,
                        hours=[
                            ScheduleHour(
                                start=local_start,
                                tiles=[
                                    _schedule_tile(cards[in_arena.pk]),
                                    _schedule_tile(cards[on_stage.pk]),
                                ],
                            ),
                            ScheduleHour(
                                start=local_start + timedelta(hours=2),
                                tiles=[_schedule_tile(cards[later_in_arena.pk])],
                            ),
                        ],
                        tiles=[
                            ScheduleTile(
                                data=cards[session.pk],
                                start=timezone.localtime(
                                    session.agenda_item.start_time
                                ),
                                end=timezone.localtime(session.agenda_item.end_time),
                            )
                            for session in (in_arena, on_stage, later_in_arena)
                        ],
                    )
                ],
                active_tab="rooms",
                room_lanes=RoomLanes(
                    rooms=[
                        RoomLane(
                            name="Arena", group="", group_key="", starts_group=True
                        ),
                        RoomLane(
                            name="Stage", group="", group_key="", starts_group=False
                        ),
                    ],
                    # The single day opens the grid, so it has no seam above
                    # it and its first hour is row 1. Four hours of lane, 10:00
                    # to 13:00: the two sessions at 10:00, an empty 11:00, the
                    # two-hour one from 12:00, and the hour it runs into.
                    rows=[
                        RoomLaneRow(
                            day=0,
                            day_start=local_start,
                            hour=local_start + timedelta(hours=offset),
                            hour_end=local_start + timedelta(hours=offset + 1),
                            starting_tiles=tiles_by_row.get(offset, []),
                        )
                        for offset in range(4)
                    ],
                    spans=[1, 2],
                    lane_indices=[0],
                    lane_counts=[1],
                ),
                has_enrollable_sessions=True,
                scheduled_count=3,
            ),
            template_name=["chronology/event.html"],
            contains=[
                "schedule-rail",
                f"?session={in_arena.pk}",
                # Both bookmark-toggle tile states render for the viewer.
                'aria-pressed="false"',
                'aria-pressed="true"',
            ],
        )
        content = response.content.decode()
        assert re.search(r">\s*Arena\s*</div>", content)
        assert re.search(r">\s*Stage\s*</div>", content)
        assert re.search(r">\s*16\+\s*<", content)

    def test_ok_compact_unknown_view_falls_back_to_list(
        self, active_user, agenda_item, client, event, monkeypatch
    ):
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )

        response = client.get(f"{self._get_url(event.slug)}?view=starfield")

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        schedule_day = _single_schedule_day(session_data)
        url = self._get_url(event.slug)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=url,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                compact_schedule=True,
                schedule_days=[schedule_day],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains="session-grid",
        )

    def test_ok_enrollment_filter_stays_off_a_schedule_without_enrollment(
        self, client, event, space
    ):
        drop_in = SessionFactory(
            event=event, category=None, participants_limit=0, min_age=0
        )
        agenda_item = AgendaItemFactory(session=drop_in, space=space)

        response = client.get(self._get_url(event.slug))

        card = session_card(agenda_item, presenter=drop_in.presenter)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                current_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=False,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_ok_live_event_card_slot_shows_now_and_propose(
        self, agenda_item, client, event
    ):
        now = timezone.now()
        event.start_time = now - timedelta(hours=2)
        event.end_time = now + timedelta(days=1)
        event.proposal_start_time = now - timedelta(days=1)
        event.proposal_end_time = now + timedelta(days=1)
        event.save()
        agenda_item.start_time = now - timedelta(minutes=30)
        agenda_item.end_time = now + timedelta(hours=1)
        agenda_item.save()

        response = client.get(self._get_url(event.slug))

        card = session_card(
            agenda_item,
            presenter=agenda_item.session.presenter,
            is_enrollment_available=True,
            is_ongoing=True,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                current_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )
        content = response.content.decode()
        assert re.search(r">\s*Now\s*</span>", content)
        assert re.search(r">\s*Propose\s*</span>", content)

    @pytest.mark.usefixtures("enrollment_config")
    def test_status_pills_capped_at_two_drops_upcoming(self, client, event):
        now = timezone.now()
        event.proposal_start_time = now - timedelta(days=1)
        event.proposal_end_time = now + timedelta(days=1)
        event.save()

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
            contains=["Enrollment Open", "Proposals Open"],
            not_contains="Upcoming",
        )

    def test_status_pill_live_event_shows_happening_now(self, client, event):
        now = timezone.now()
        event.start_time = now - timedelta(hours=1)
        event.end_time = now + timedelta(hours=1)
        event.save()

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
            contains="Happening now!",
            not_contains="Upcoming",
        )

    def test_status_pill_ended_event_shows_completed(self, client, event):
        now = timezone.now()
        event.start_time = now - timedelta(hours=2)
        event.end_time = now - timedelta(hours=1)
        event.save()

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
            contains="Completed",
            not_contains="Upcoming",
        )

    def test_ok_session_card_exposes_day_and_hour_data_attributes(
        self, active_user, agenda_item, client, event
    ):
        """Cards expose day/hour data attributes powering client-side filters."""
        session = agenda_item.session

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )
        local_start = timezone.localtime(agenda_item.start_time)
        content = response.content.decode()
        day = local_start.strftime("%Y-%m-%d")
        hour = local_start.strftime("%H:%M")
        match = re.search(
            rf'data-day="{re.escape(day)}"\s+data-day-label="([^"]+)"\s+data-hour="{re.escape(hour)}"',
            content,
        )
        assert match
        assert match.group(1)

    def test_track_and_category_filters_expose_data_and_controls(
        self, client, event, space
    ):
        category_a = ProposalCategoryFactory(event=event, name="RPG", slug="rpg")
        category_b = ProposalCategoryFactory(
            event=event, name="Board games", slug="board"
        )
        track_a = Track.objects.create(
            event=event, name="Main Hall", slug="main", is_public=True
        )
        track_b = Track.objects.create(
            event=event, name="Side Room", slug="side", is_public=True
        )
        session_a = SessionFactory(event=event, category=category_a, min_age=0)
        session_a.tracks.add(track_a)
        session_b = SessionFactory(event=event, category=category_b, min_age=0)
        session_b.tracks.add(track_b)
        item_a = AgendaItemFactory(session=session_a, space=space)
        # Off item_a, not off a floating now: the factory anchors item_a to
        # 10:00 local precisely so an item cannot drift across midnight, and
        # `now + 3h` gives that back. Run between 00:00 and 07:00 local,
        # `now + 3h` is still before 10:00, so b sorted ahead of a and the
        # expected order flipped — red every night from 22:00 UTC.
        item_b = AgendaItemFactory(
            session=session_b,
            space=space,
            start_time=item_a.start_time + timedelta(hours=3),
        )
        cards = [
            session_card(
                item_a,
                presenter=session_a.presenter,
                category_name=category_a.name,
                track_names=[track_a.name],
            ),
            session_card(
                item_b,
                presenter=session_b.presenter,
                category_name=category_b.name,
                track_names=[track_b.name],
            ),
        ]
        hour_data = {item_a.start_time: [cards[0]], item_b.start_time: [cards[1]]}

        response = client.get(self._get_url(event.slug))

        # Both filters list every value in use — they render only when a field
        # has more than one, so two names each is what puts the controls up.
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data=hour_data,
                future_unavailable_hour_data=hour_data,
                sessions=cards,
                track_filter_names=[track_a.name, track_b.name],
                category_filter_names=[category_b.name, category_a.name],
                has_enrollable_sessions=True,
                scheduled_count=len(cards),
            ),
            template_name=["chronology/event.html"],
        )

    def test_schedule_hides_sessions_with_any_private_track(self, client, event, space):
        public_track = Track.objects.create(
            event=event, name="Main Hall", slug="main", is_public=True
        )
        private_track = Track.objects.create(
            event=event, name="Backstage", slug="backstage", is_public=False
        )
        # Named categories, not faker-worded: these two are the whole of the
        # category filter below, and both drawing the same word would leave
        # the view one name and the expectation two.
        untracked = SessionFactory(
            event=event, category=ProposalCategoryFactory(event=event, name="RPG")
        )
        public_only = SessionFactory(
            event=event,
            category=ProposalCategoryFactory(event=event, name="Board games"),
        )
        public_only.tracks.add(public_track)
        mixed = SessionFactory(event=event)
        mixed.tracks.add(public_track, private_track)
        private_only = SessionFactory(event=event)
        private_only.tracks.add(private_track)
        items = {
            session: AgendaItemFactory(session=session, space=space)
            for session in (untracked, public_only, mixed, private_only)
        }
        visible = [
            session_card(
                items[untracked],
                presenter=untracked.presenter,
                category_name=untracked.category.name,
            ),
            session_card(
                items[public_only],
                presenter=public_only.presenter,
                category_name=public_only.category.name,
                track_names=["Main Hall"],
            ),
        ]
        # The factory staggers agenda items by a microsecond, so each visible
        # session lands in its own bucket.
        hour_data = {
            items[untracked].start_time: [visible[0]],
            items[public_only].start_time: [visible[1]],
        }

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data=hour_data,
                future_unavailable_hour_data=hour_data,
                sessions=visible,
                category_filter_names=sorted(
                    session.category.name for session in (untracked, public_only)
                ),
                has_enrollable_sessions=True,
                scheduled_count=len(visible),
            ),
            template_name=["chronology/event.html"],
        )

    @pytest.mark.usefixtures("panel_access_user")
    def test_schedule_hides_private_tracks_from_panel_access_too(
        self, authenticated_client, event, space
    ):
        event.publication_time = None
        event.save()
        private_track = Track.objects.create(
            event=event, name="Backstage", slug="backstage", is_public=False
        )
        private_only = SessionFactory(event=event)
        private_only.tracks.add(private_track)
        AgendaItemFactory(session=private_only, space=space)

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )

    def test_shows_event_cover_image(self, client, event):
        event.cover_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        event.save()

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )

    def test_session_card_hides_age_pill_when_min_age_zero(
        self, agenda_item, client, event
    ):
        session = agenda_item.session
        session.min_age = 0
        session.save()

        response = client.get(self._get_url(event.slug))

        card = session_card(agenda_item, presenter=session.presenter)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            not_contains="All ages",
        )

    def test_session_card_shows_overflow_tag_trigger(self, agenda_item, client, event):
        session_field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Genre",
            slug="genre",
            field_type="select",
            is_multiple=True,
            is_public=True,
        )
        self._add_choices(session_field, "a", "b", "c", "d", "e")
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=["a", "b", "c", "d", "e"]
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="",
            field_id=session_field.pk,
            field_name="Genre",
            field_question="Genre",
            field_slug="genre",
            field_type="select",
            is_public=True,
            value=["a", "b", "c", "d", "e"],
        )
        card = session_card(
            agenda_item,
            presenter=session.presenter,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            field_values=[field_value_dto],
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                filterable_tag_categories=[_field_dto(session_field)],
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains=["session-tags-more", "+1"],
        )

    def _add_scheduled_session(self, *, event, space, session_field, values=("a", "b")):
        presenter = UserFactory()
        session = SessionFactory(
            presenter=presenter,
            display_name=presenter.name,
            event=event,
            # Named, not faker-worded: `_tagged_page_context` expects one
            # filter name per session, and the view offers the distinct names
            # only. Two sessions drawing the same word out of the faker list
            # shorten the view's list without shortening the expected one.
            category=ProposalCategoryFactory(
                event=event, name=f"category-{event.proposal_categories.count()}"
            ),
            participants_limit=10,
            min_age=0,
        )
        AgendaItemFactory(session=session, space=space)
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=list(values)
        )
        SessionParticipation.objects.create(
            session=session,
            user=UserFactory(),
            status=SessionParticipationStatus.CONFIRMED,
        )
        session.refresh_from_db()
        return session

    @classmethod
    def _tagged_page_context(
        cls,
        event,
        *,
        url,
        sessions,
        session_field,
        scheduled_count,
        values=("a", "b"),
        allow_custom=False,
        filterable=True,
    ):
        cards = [
            cls._tagged_card(
                session,
                session_field=session_field,
                values=values,
                allow_custom=allow_custom,
            )
            for session in sessions
        ]
        hour_data = {}
        for session, card in zip(sessions, cards, strict=True):
            hour_data.setdefault(session.agenda_item.start_time, []).append(card)
        return event_page_context(
            event,
            url=url,
            filterable_tag_categories=[_field_dto(session_field)] if filterable else [],
            category_filter_names=sorted(s.category.name for s in sessions),
            hour_data=hour_data,
            future_unavailable_hour_data=hour_data,
            sessions=cards,
            total_enrolled=len(cards),
            has_enrollable_sessions=True,
            scheduled_count=scheduled_count,
        )

    @staticmethod
    def _tagged_card(session, *, session_field, values=("a", "b"), allow_custom=False):
        field_value_dto = SessionFieldValueDTO(
            allow_custom=allow_custom,
            field_icon="",
            field_id=session_field.pk,
            field_name="Genre",
            field_question="Genre",
            field_slug="genre",
            field_type="select",
            is_public=True,
            value=list(values),
        )
        return session_card(
            session.agenda_item,
            presenter=session.presenter,
            enrolled_count=1,
            category_name=session.category.name,
            # The field is public but not on the event's displayed list, so it
            # reaches the card's values without a display row.
            field_values=[field_value_dto],
            session_participations=[
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(participation.user),
                        gravatar_url=gravatar_url,
                    ),
                    status=participation.status,
                    creation_time=participation.creation_time,
                    is_shadowbanned=False,
                )
                for participation in SessionParticipation.objects.filter(
                    session=session
                ).select_related("user")
            ],
        )

    @staticmethod
    def _add_choices(session_field, *values):
        for order, value in enumerate(values):
            SessionFieldOption.objects.create(
                field=session_field, value=value, label=value, order=order
            )

    def test_ok_filter_panel_leaves_out_a_field_nobody_answered(
        self, client, event, space
    ):
        genre = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Genre",
            slug="genre",
            field_type="select",
            is_multiple=True,
            is_public=True,
        )
        self._add_choices(genre, "a", "b")
        SessionField.objects.create(
            event=event,
            name="Format",
            question="Format",
            slug="format",
            field_type="select",
            is_multiple=True,
            is_public=True,
        )
        sessions = [
            self._add_scheduled_session(event=event, space=space, session_field=genre)
            for _ in range(2)
        ]

        response = client.get(self._get_url(event.slug))

        # Both fields are public selects on the event; only Genre is answered,
        # so only Genre reaches the panel.
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._tagged_page_context(
                event,
                url=self._get_url(event.slug),
                sessions=sessions,
                session_field=genre,
                scheduled_count=2,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_filter_panel_leaves_out_a_field_answered_only_with_write_ins(
        self, client, event, space
    ):
        genre = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Genre",
            slug="genre",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
            is_public=True,
        )
        self._add_choices(genre, "a")
        written_in = ("gritty", "kalamburowy")
        sessions = [
            self._add_scheduled_session(
                event=event, space=space, session_field=genre, values=written_in
            )
            for _ in range(2)
        ]

        response = client.get(self._get_url(event.slug))

        # Two distinct answers, but neither is one of the field's choices, so
        # the dropdown would have had nothing to offer.
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._tagged_page_context(
                event,
                url=self._get_url(event.slug),
                sessions=sessions,
                session_field=genre,
                scheduled_count=2,
                values=written_in,
                allow_custom=True,
                filterable=False,
            ),
            template_name=["chronology/event.html"],
        )

    def test_query_count_constant_in_session_count(self, client, event, space):
        session_field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Genre",
            slug="genre",
            field_type="select",
            is_multiple=True,
            is_public=True,
        )
        self._add_choices(session_field, "a", "b")
        sessions = [
            self._add_scheduled_session(
                event=event, space=space, session_field=session_field
            )
            for _ in range(2)
        ]
        client.get(self._get_url(event.slug))

        with CaptureQueriesContext(connection) as small_event_queries:
            response = client.get(self._get_url(event.slug))
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._tagged_page_context(
                event,
                url=self._get_url(event.slug),
                sessions=sessions,
                session_field=session_field,
                scheduled_count=2,
            ),
            template_name=["chronology/event.html"],
        )

        sessions += [
            self._add_scheduled_session(
                event=event, space=space, session_field=session_field
            )
            for _ in range(6)
        ]

        with CaptureQueriesContext(connection) as big_event_queries:
            response = client.get(self._get_url(event.slug))
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._tagged_page_context(
                event,
                url=self._get_url(event.slug),
                sessions=sessions,
                session_field=session_field,
                scheduled_count=8,
            ),
            template_name=["chronology/event.html"],
        )

        assert len(big_event_queries.captured_queries) == len(
            small_event_queries.captured_queries
        )

    def test_shows_session_cover_image(self, active_user, agenda_item, client, event):
        session = agenda_item.session
        session.cover_image = SimpleUploadedFile(
            "session.png", PNG_BYTES, content_type="image/png"
        )
        session.save()

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )
        assert session.cover_image_url.encode() in response.content

    def test_hides_placeholder_cover_when_session_has_no_image_by_default(
        self, agenda_item, client, event
    ):
        session = agenda_item.session
        assert not session.cover_image_url

        response = client.get(self._get_url(event.slug))

        card = session_card(agenda_item, presenter=session.presenter)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            not_contains=placeholder_cover_url(session.pk),
        )

    def test_shows_placeholder_cover_when_event_opts_in(
        self, agenda_item, client, event
    ):
        event.use_session_cover_placeholders = True
        event.save(update_fields=["use_session_cover_placeholders"])
        session = agenda_item.session
        assert not session.cover_image_url

        response = client.get(self._get_url(event.slug))

        card = session_card(agenda_item, presenter=session.presenter)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains=placeholder_cover_url(session.pk),
        )

    def test_closed_call_for_proposals_builds_no_review_queue(
        self, authenticated_client, event, active_user, pending_session
    ):
        # The event fixture's CFP has already shut. The block does not render
        # then, so the cards are not built either — they used to be, and
        # discarded in the template.
        assert not event.is_proposal_active
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )

    def test_ok_superuser_sees_preferred_slots_earliest_first(
        self, authenticated_client, event, active_user, pending_session
    ):
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        # Added latest-first, so a card that echoed insertion order would fail.
        slots = [
            TimeSlotFactory(
                event=event, start_time=event.start_time + timedelta(hours=offset)
            )
            for offset in reversed(_PREFERRED_SLOT_OFFSETS)
        ]
        pending_session.time_slots.add(*slots)
        flexible_session = SessionFactory(
            category=pending_session.category,
            presenter=active_user,
            display_name=active_user.name,
            participants_limit=5,
            min_age=0,
            status="pending",
        )

        response = authenticated_client.get(self._get_url(event.slug))

        expected_flexible = proposal_card(
            flexible_session, presenter=active_user, can_edit=True
        )
        expected_pending = proposal_card(
            pending_session,
            presenter=active_user,
            can_edit=True,
            slots=sorted(slots, key=lambda slot: slot.start_time),
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                pending_sessions=[expected_flexible, expected_pending],
                pending_review_visible=True,
                pending_wizard_view=True,
            ),
            template_name=["chronology/event.html"],
        )

    def test_review_inbox_query_count_constant_in_proposal_count(
        self, authenticated_client, event, active_user, pending_session
    ):
        # The review queue is unbounded, so it has to cost the same at 1 and at
        # 5. It doesn't for free: the card reads enrolled_count/waiting_count,
        # which fall back to a COUNT per instance unless the queryset carries
        # annotate_session_participation_counts. zeal can't catch that — it
        # instruments relation traversal, not .count() on a related manager.
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])

        # Warm up first, as the scheduled-session counterpart above does: one-off
        # per-process work would otherwise land inside the smaller capture.
        authenticated_client.get(self._get_url(event.slug))

        with CaptureQueriesContext(connection) as one_proposal:
            first = authenticated_client.get(self._get_url(event.slug))

        for _ in range(4):
            SessionFactory(
                category=pending_session.category,
                presenter=active_user,
                display_name=active_user.name,
                participants_limit=5,
                min_age=0,
                status="pending",
            )

        with CaptureQueriesContext(connection) as five_proposals:
            last = authenticated_client.get(self._get_url(event.slug))

        # Both responses are asserted, or a queue that quietly stopped
        # rendering would satisfy the count comparison perfectly.
        assert first.status_code == HTTPStatus.OK
        assert len(first.context["pending_sessions"]) == 1
        assert last.status_code == HTTPStatus.OK
        assert len(last.context["pending_sessions"]) == _PROPOSALS_IN_QUEUE
        assert len(five_proposals.captured_queries) == len(
            one_proposal.captured_queries
        )

    def test_ok_superuser_organizer_sees_no_wizard_emoji(
        self, authenticated_client, event, active_user, pending_session
    ):
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        event.sphere.managers.add(active_user)
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])

        response = authenticated_client.get(self._get_url(event.slug))

        expected_pending = proposal_card(
            pending_session, presenter=active_user, can_edit=True
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                pending_sessions=[expected_pending],
                pending_review_visible=True,
            ),
            template_name=["chronology/event.html"],
            not_contains="🧙",
        )

    def test_ok_manager_sees_pending_proposals_without_wizard_emoji(
        self, authenticated_client, event, active_user, pending_session
    ):
        event.sphere.managers.add(active_user)
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])

        response = authenticated_client.get(self._get_url(event.slug))

        expected_pending = proposal_card(
            pending_session, presenter=active_user, can_edit=True
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                pending_sessions=[expected_pending],
                pending_review_visible=True,
            ),
            template_name=["chronology/event.html"],
            not_contains="🧙",
        )

    def test_shadowbanned_presenter_is_flagged_on_their_proposal_card(
        self, authenticated_client, event, active_user, pending_session
    ):
        # The same presenter must not be ringed on a scheduled card and clean
        # on a proposal: both card sets read the viewer's shadowban list.
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        presenter = UserFactory()
        pending_session.presenter = presenter
        pending_session.save(update_fields=["presenter"])
        active_user.shadowbanned.add(presenter)

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                pending_sessions=[
                    proposal_card(
                        pending_session,
                        presenter=presenter,
                        presenter_is_shadowbanned=True,
                    )
                ],
                pending_review_visible=True,
                pending_wizard_view=True,
            ),
            template_name=["chronology/event.html"],
        )

    def test_proposal_without_a_category_still_reaches_the_review_queue(
        self, authenticated_client, event, active_user, pending_session
    ):
        # Session.category is nullable, so scoping the queue through it would
        # drop this proposal from the organizer's view and its author's alike.
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        pending_session.category = None
        pending_session.save(update_fields=["category"])

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                pending_sessions=[
                    proposal_card(pending_session, presenter=active_user, can_edit=True)
                ],
                pending_review_visible=True,
                pending_wizard_view=True,
            ),
            template_name=["chronology/event.html"],
        )

    def test_scheduled_pending_session_is_not_offered_for_review(
        self, authenticated_client, event, active_user, pending_session, space
    ):
        # A pending session already on the timetable cannot be accepted:
        # accepting creates an AgendaItem and a session may only have one. It
        # belongs to the panel, not to the event page's review inbox.
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        agenda_item = AgendaItemFactory(
            session=pending_session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = authenticated_client.get(self._get_url(event.slug))

        # It leaves the review inbox and joins the programme instead.
        card = session_card(
            agenda_item,
            presenter=active_user,
            can_edit=True,
            category_name=pending_session.category.name,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                scheduled_count=1,
                has_enrollable_sessions=True,
                pending_review_visible=True,
                pending_wizard_view=True,
            ),
            template_name=["chronology/event.html"],
        )

    def test_author_loses_sight_of_a_proposal_scheduled_into_a_private_track(
        self, authenticated_client, event, active_user, pending_session, space
    ):
        # A recorded trade-off, not an accident. Both proposal lists mean
        # "not on the timetable", because a scheduled session commonly keeps
        # PENDING and status alone would pull the author's whole programme in
        # here. The cost is this corner: scheduled into a private track, the
        # session is hidden from the public schedule too, so its own author
        # sees it nowhere on this page. The panel still shows it.
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        AgendaItemFactory(
            session=pending_session,
            space=space,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )
        pending_session.tracks.add(
            Track.objects.create(
                event=event, name="Backstage", slug="backstage", is_public=False
            )
        )

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )

    def test_ok_proposal_author_sees_own_proposal_card(
        self, authenticated_client, event, active_user, pending_session
    ):
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        assert pending_session.presenter == active_user

        response = authenticated_client.get(self._get_url(event.slug))

        expected_card = proposal_card(
            pending_session, presenter=active_user, can_edit=True
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                own_pending_proposals=[expected_card],
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_proposal_card_names_its_private_track(
        self, authenticated_client, event, active_user, pending_session
    ):
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        pending_session.tracks.add(
            Track.objects.create(
                event=event, name="Backstage", slug="backstage", is_public=False
            )
        )

        response = authenticated_client.get(self._get_url(event.slug))

        expected_card = proposal_card(
            pending_session,
            presenter=active_user,
            can_edit=True,
            track_names=["Backstage"],
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                own_pending_proposals=[expected_card],
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_participations(
        self, authenticated_client, event, active_user, session, companion, agenda_item
    ):
        part1 = SessionParticipation.objects.create(
            session=session,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        part2 = SessionParticipation.objects.create(
            session=session, user=companion, status=SessionParticipationStatus.WAITING
        )
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(session.agenda_item),
            effective_participants_limit=10,
            enrolled_count=1,
            waiting_count=1,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(part1.user), gravatar_url=gravatar_url
                    ),
                    status=part1.status,
                    creation_time=part1.creation_time,
                ),
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(part2.user), gravatar_url=gravatar_url
                    ),
                    status=part2.status,
                    creation_time=part2.creation_time,
                ),
            ],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(session.agenda_item.space),
            user_enrolled=True,
            user_waiting=True,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                total_enrolled=1,
                user_enrolled_sessions=[session_data],
                user_enrolled_session_titles=[session_data.session.title],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )
        assert "Companions" not in response.content.decode()

    def test_ok_session_with_linked_proposal(
        self, active_user, agenda_item, client, event, session
    ):
        host = UserInfo.from_user_dto(
            UserDTO.model_validate(active_user), gravatar_url=gravatar_url
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=host,
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_session_without_enrollment(
        self, active_user, agenda_item, client, event, session
    ):
        session.participants_limit = 0
        session.save()

        host = UserInfo.from_user_dto(
            UserDTO.model_validate(active_user), gravatar_url=gravatar_url
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=0,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=host,
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_session_without_presenter_user(self, client, event, space):
        display_name = "External Presenter"
        session = SessionFactory(
            presenter=None,
            display_name=display_name,
            event=event,
            participants_limit=10,
            min_age=0,
        )
        agenda_item = AgendaItemFactory(session=session, space=space)

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo(
                avatar_url=None,
                discord_username="",
                full_name=display_name,
                name=display_name,
                pk=0,
                slug="",
                username=display_name,
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
            category_name=session.category.name,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_ended_session(self, active_user, agenda_item, client, event, faker):
        agenda_item.start_time = faker.date_time_between("-20d", "-10d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("-9d", "-1d", tzinfo=UTC)
        agenda_item.save()
        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=True,
            is_ended=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                ended_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session(self, active_user, agenda_item, client, event, faker):
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_reset_anonymous_enrollment(self, authenticated_client, event):
        session = authenticated_client.session
        session["anonymous_user_code"] = 123
        session["anonymous_enrollment_active"] = 123
        session["anonymous_event_id"] = 123
        session["anonymous_site_id"] = 123
        session.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )
        assert not authenticated_client.session.get("anonymous_user_code")
        assert not authenticated_client.session.get("anonymous_enrollment_active")
        assert not authenticated_client.session.get("anonymous_event_id")
        assert not authenticated_client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active(
        self, anonymous_user_factory, client, event, settings
    ):
        session = client.session
        user = anonymous_user_factory()
        session["anonymous_user_code"] = user.slug.split("_")[1]
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = event.sphere.site.pk
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                anonymous_code=user.slug.split("_")[1],
                anonymous_user_enrollments=[],
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_anonymous_enrollment_active_no_user(self, client, event, settings):
        session = client.session
        session["anonymous_user_code"] = 17
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = event.sphere.site.pk
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active_wrong_site(self, client, event, settings):
        session = client.session
        session["anonymous_user_code"] = 17
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = "nosite"
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active_no_user_id(self, client, event, settings):
        session = client.session
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = "nosite"
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active_wrong_user_id(
        self, client, event, settings
    ):
        session = client.session
        session["anonymous_user_code"] = "notanid"
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = "nosite"
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=self._get_url(event.slug)),
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_with_participation(
        self, active_user, agenda_item, anonymous_user_factory, client, event, settings
    ):
        session = client.session
        user = anonymous_user_factory()
        participation = SessionParticipation.objects.create(
            user=user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        session["anonymous_user_code"] = user.slug.split("_")[1]
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = event.sphere.site.pk
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=1,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(participation.user),
                        gravatar_url=gravatar_url,
                    ),
                    status=participation.status,
                    creation_time=participation.creation_time,
                )
            ],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=True,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                anonymous_code=user.slug.split("_")[1],
                anonymous_user_enrollments=[participation],
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                total_enrolled=1,
                user_enrolled_sessions=[session_data],
                user_enrolled_session_titles=[session_data.session.title],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session_enrollment_config_limit(
        self, active_user, agenda_item, client, enrollment_config, event, faker
    ):
        enrollment_config.limit_to_end_time = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=True,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @pytest.mark.parametrize("fetched_from_api", (True, False))
    def test_ok_current_session_sum_time_slots(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        fetched_from_api,
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        other_config = EnrollmentConfig.objects.create(
            event=event,
            start_time=faker.date_time_between("-3d", "-1d"),
            end_time=faker.date_time_between("+1d", "+3d"),
            percentage_slots=100,
            restrict_to_configured_users=True,
        )
        primary_slots = 7
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=primary_slots,
            fetched_from_api=fetched_from_api,
        )
        other_slots = 8
        UserEnrollmentConfig.objects.create(
            enrollment_config=other_config,
            user_email=active_user.email,
            allowed_slots=other_slots,
            fetched_from_api=fetched_from_api,
        )
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=7 + 8, user_slots=7 + 8, has_user_config=True
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains="Enrollment Open",
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        slots = 7
        responses.get(
            url=MEMBERSHIP_API_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": slots},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=slots, user_slots=slots, has_user_config=True
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_domain_config(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        responses.get(
            url=MEMBERSHIP_API_URL,
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
        )
        slots = 7
        DomainEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            domain=active_user.email.split("@")[1],
            allowed_slots_per_user=slots,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=slots,
                    user_slots=0,
                    domain=active_user.email.split("@")[1],
                    has_user_config=False,
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session_domain_config_combined_with_user(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
    ):
        primary_slots = 8
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=primary_slots,
        )
        domain_slots = 7
        DomainEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            domain=active_user.email.split("@")[1],
            allowed_slots_per_user=domain_slots,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=primary_slots + domain_slots,
                    user_slots=primary_slots,
                    domain=active_user.email.split("@")[1],
                    has_user_config=True,
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_http_error(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        responses.get(
            url=MEMBERSHIP_API_URL,
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": 7},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_json_error(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        responses.get(
            url=MEMBERSHIP_API_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json=["a"],
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_refetch(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-10d", "-5d"),
        )
        slots = 7
        responses.get(
            url=MEMBERSHIP_API_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": slots},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=slots,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=slots, user_slots=slots, has_user_config=True
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_without_ticketing_integration_skips_the_api(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
    ):
        # No integration configured and a stale check: the slots the organizer
        # entered by hand still count, and nothing is fetched. `responses` has
        # no registered endpoint, so any outbound call fails the test.
        slots = 7
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=slots,
            last_check=faker.date_time_between("-10d", "-5d"),
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()

        response = authenticated_client.get(self._get_url(event.slug))

        assert not responses.calls
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=slots, user_slots=slots, has_user_config=True
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session_get_user_config_from_api_no_refetch(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-1m", "now"),
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=0, user_slots=0, has_user_config=True
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_refetch_zero(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-10d", "-5d"),
        )
        responses.get(
            url=MEMBERSHIP_API_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": 0},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=0, user_slots=0, has_user_config=True
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_zero(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        ticketing_integration,
    ):
        responses.get(
            url=MEMBERSHIP_API_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": 0},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                current_hour_data={agenda_item.start_time: [session_data]},
                enrollment_requires_slots=True,
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                user_enrollment_config=VirtualEnrollmentConfig(
                    allowed_slots=0, user_slots=0, has_user_config=True
                ),
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_displayed_field_values(
        self, active_user, agenda_item, client, event
    ):
        """Select field values are shown on cards when the field is displayed."""
        session_field = SessionField.objects.create(
            event=event,
            name="Game Type",
            question="Game Type",
            slug="game-type",
            field_type="select",
            is_multiple=True,
            is_public=True,
            icon="puzzle-piece",
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=["RPG"]
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="puzzle-piece",
            field_id=session_field.pk,
            field_name="Game Type",
            field_question="Game Type",
            field_slug="game-type",
            field_type="select",
            is_public=True,
            value=["RPG"],
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            field_values=[field_value_dto],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_overflowing_field_values_shows_popover(
        self, agenda_item, client, event
    ):
        """Values past the visible limit collapse into a hover popover."""
        session = agenda_item.session
        session_field = SessionField.objects.create(
            event=event,
            name="Game Type",
            question="Game Type",
            slug="game-type",
            field_type="select",
            is_multiple=True,
            is_public=True,
            icon="puzzle-piece",
        )
        self._add_choices(
            session_field, "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"
        )
        SessionFieldValue.objects.create(
            session=session,
            field=session_field,
            value=["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"],
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="puzzle-piece",
            field_id=session_field.pk,
            field_name="Game Type",
            field_question="Game Type",
            field_slug="game-type",
            field_type="select",
            is_public=True,
            value=["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"],
        )
        card = session_card(
            agenda_item,
            presenter=session.presenter,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            field_values=[field_value_dto],
        )
        # Four values stay visible; the two extras collapse into the "+N" popover.
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                filterable_tag_categories=[_field_dto(session_field)],
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains=["+2", "Echo", "Foxtrot"],
        )

    def test_ok_session_with_non_displayed_field_excluded_from_rows(
        self, active_user, agenda_item, client, event
    ):
        """Field values not in displayed_session_fields are excluded from rows."""
        session_field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system?",
            slug="rpg-system",
            field_type="text",
            is_public=True,
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value="D&D 5e"
        )

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            field_values=[
                SessionFieldValueDTO(
                    allow_custom=False,
                    field_icon="",
                    field_id=session_field.pk,
                    field_name="RPG System",
                    field_question="What RPG system?",
                    field_slug="rpg-system",
                    field_type="text",
                    is_public=True,
                    value="D&D 5e",
                )
            ],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_displayed_text_field(
        self, active_user, agenda_item, client, event
    ):
        """Text field values appear on cards when field is displayed."""
        session_field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system?",
            slug="rpg-system",
            field_type="text",
            is_public=True,
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value="D&D 5e"
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="",
            field_id=session_field.pk,
            field_name="RPG System",
            field_question="What RPG system?",
            field_slug="rpg-system",
            field_type="text",
            is_public=True,
            value="D&D 5e",
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            field_values=[field_value_dto],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_displayed_checkbox_field(
        self, active_user, agenda_item, client, event
    ):
        """Checkbox field values appear on cards when field is displayed."""
        session_field = SessionField.objects.create(
            event=event,
            name="Beginner Friendly",
            question="Is this beginner friendly?",
            slug="beginner-friendly",
            field_type="checkbox",
            is_public=True,
            icon="academic-cap",
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=True
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="academic-cap",
            field_id=session_field.pk,
            field_name="Beginner Friendly",
            field_question="Is this beginner friendly?",
            field_slug="beginner-friendly",
            field_type="checkbox",
            is_public=True,
            value=True,
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=location_data(agenda_item.space),
            field_values=[field_value_dto],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    # Unpublished events are not 404s but redirects to the events list: the 404
    # fallback routes missing and unpublished events identically so a response
    # never reveals whether an unannounced event exists. See
    # TestSemantic404Recovery in tests/integration/web/test_error_views.py.
    def test_unpublished_event_redirects_anonymous_to_events_list(self, client, sphere):
        event = EventFactory(sphere=sphere, publication_time=None)

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:events"),
            messages=[(messages.INFO, "That event isn't available.")],
        )

    def test_unpublished_event_redirects_regular_user_to_events_list(
        self, authenticated_client, sphere
    ):
        event = EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:events"),
            messages=[(messages.INFO, "That event isn't available.")],
        )

    def test_unpublished_event_visible_for_manager_and_superuser(
        self, authenticated_client, panel_access_user, sphere
    ):
        event = EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                pending_review_visible=True,
                pending_wizard_view=panel_access_user.is_superuser,
            ),
            template_name=["chronology/event.html"],
        )

    def test_superuser_who_manages_sphere_gets_manager_view(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        active_user.is_superuser = True
        active_user.save()
        event = EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event, url=self._get_url(event.slug), pending_review_visible=True
            ),
            template_name=["chronology/event.html"],
        )


class TestEventPageEditAffordance:
    URL_NAME = "web:chronology:event"

    def _get_url(self, slug):
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def _scheduled_session(self, event, presenter):
        category = ProposalCategoryFactory(event=event)
        return SessionFactory(
            category=category,
            presenter=presenter,
            display_name=presenter.name,
            participants_limit=10,
            min_age=0,
            status="accepted",
        )

    def _assert_edit_affordance(self, response, *, event, agenda_item, can_edit):
        card = session_card(
            agenda_item,
            presenter=agenda_item.session.presenter,
            can_edit=can_edit,
            category_name=agenda_item.session.category.name,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_owner_sees_edit_affordance(
        self, authenticated_client, event, active_user, space
    ):
        session = self._scheduled_session(event, active_user)
        agenda_item = AgendaItemFactory(session=session, space=space)
        edit_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event.slug, "session_id": session.pk},
        )

        response = authenticated_client.get(self._get_url(event.slug))

        self._assert_edit_affordance(
            response, event=event, agenda_item=agenda_item, can_edit=True
        )
        # The edit button lives in the lazy-loaded session modal, not the page.
        modal = authenticated_client.get(
            reverse(
                "web:chronology:session-modal",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            )
        )
        assert_rendered(
            response=modal,
            template_name="chronology/parts/session-modal.html",
            contains=[edit_url, f'data-edit-open="{session.pk}"'],
        )

    def test_non_owner_no_edit_affordance(self, authenticated_client, event, space):
        other = UserFactory(username="other", email="other@example.com")
        session = self._scheduled_session(event, other)
        agenda_item = AgendaItemFactory(session=session, space=space)

        response = authenticated_client.get(self._get_url(event.slug))

        self._assert_edit_affordance(
            response, event=event, agenda_item=agenda_item, can_edit=False
        )

    def test_owner_no_affordance_when_opted_out(
        self, authenticated_client, event, active_user, space
    ):
        event.allow_facilitator_session_edit = False
        event.save()
        session = self._scheduled_session(event, active_user)
        agenda_item = AgendaItemFactory(session=session, space=space)

        response = authenticated_client.get(self._get_url(event.slug))

        self._assert_edit_affordance(
            response, event=event, agenda_item=agenda_item, can_edit=False
        )


class TestPublicEventUrlShape:
    def test_event_url_has_no_chronology_segment(self, event):
        url = reverse("web:chronology:event", kwargs={"slug": event.slug})

        assert url == f"/event/{event.slug}/"

    def test_new_event_url_resolves_and_renders(self, client, event):
        match = resolve(f"/event/{event.slug}/")

        assert match.view_name == "web:chronology:event"
        assert match.func.view_class is EventPageView
        assert client.get(f"/event/{event.slug}/").status_code == HTTPStatus.OK

    def test_legacy_chronology_url_redirects_permanently(self, client, event):
        response = client.get(f"/chronology/event/{event.slug}/")

        assert_response(
            response, HTTPStatus.MOVED_PERMANENTLY, url=f"/event/{event.slug}/"
        )

    def test_legacy_chronology_subpath_preserves_query_string(self, client, event):
        response = client.get(f"/chronology/event/{event.slug}/session/propose/?step=2")

        assert_response(
            response,
            HTTPStatus.MOVED_PERMANENTLY,
            url=f"/event/{event.slug}/session/propose/?step=2",
        )
