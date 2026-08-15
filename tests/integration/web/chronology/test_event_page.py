import re
from dataclasses import replace
from datetime import UTC, timedelta
from http import HTTPStatus

import pytest
import responses
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
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
    RoomLaneDay,
    RoomLaneHourMark,
    RoomLaneTile,
    ScheduleDay,
    ScheduleHour,
    ScheduleTile,
)
from ludamus.gates.web.django.entities import UserInfo
from ludamus.gates.web.django.helpers import placeholder_cover_url
from ludamus.links.db.django.models import (
    DomainEnrollmentConfig,
    EnrollmentConfig,
    EventSettings,
    SessionBookmark,
    SessionField,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
    Track,
    UserEnrollmentConfig,
)
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import (
    AgendaItemDTO,
    LocationData,
    PendingSessionDTO,
    PendingSessionTimeSlotDTO,
    SessionDTO,
    SessionFieldValueDTO,
    VirtualEnrollmentConfig,
)
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
from tests.integration.utils import assert_response
from tests.integration.web.chronology.helpers import (
    compact_day,
    event_page_context,
    make_half_full_session,
    session_card,
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
        session = make_half_full_session(event)

        response = client.get(self._get_url(event.slug))

        sessions = response.context_data["sessions"]
        card = next(item for item in sessions if item.session.pk == session.pk)
        assert card.is_full
        assert card.enrolled_count == session.participants_limit

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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        # Sections bucket whole local-clock hours, not exact start times.
        hour_start = timezone.localtime(agenda_item.start_time).replace(
            minute=0, second=0, microsecond=0
        )
        schedule_day = ScheduleDay(
            day_start=hour_start,
            hours=[ScheduleHour(start=hour_start, sessions=[session_data])],
            tiles=[
                ScheduleTile(
                    data=session_data,
                    start=timezone.localtime(agenda_item.start_time),
                    end=timezone.localtime(agenda_item.end_time),
                )
            ],
        )
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        hour_start = timezone.localtime(agenda_item.start_time).replace(
            minute=0, second=0, microsecond=0
        )
        schedule_day = ScheduleDay(
            day_start=hour_start,
            hours=[ScheduleHour(start=hour_start, sessions=[session_data])],
            tiles=[
                ScheduleTile(
                    data=session_data,
                    start=timezone.localtime(agenda_item.start_time),
                    end=timezone.localtime(agenda_item.end_time),
                )
            ],
        )
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
            ),
            template_name=["chronology/event.html"],
            not_contains="Not Available",
        )

    # Pinned: the ongoing session spans now±1h, so a run near local midnight
    # would split it across two dates and yield an extra schedule day. The
    # fixture's dates were built against the real clock, so they move too.
    @freeze_time("2026-06-15 12:00:00")
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
        unlimited = scheduled(
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
        ended = scheduled(
            start=now - timedelta(hours=3),
            end=now - timedelta(hours=2),
            participants_limit=4,
            min_age=0,
        )
        ongoing = scheduled(
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
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
                full_participant_info="4/5",
            ),
            unlimited.pk: session_card(
                unlimited.agenda_item,
                presenter=unlimited.presenter,
                is_enrollment_available=True,
                full_participant_info="0",
            ),
            full.pk: session_card(
                full.agenda_item,
                presenter=full.presenter,
                is_enrollment_available=True,
                enrolled_count=2,
                full_participant_info="2/2, 1 waiting",
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
            for session in (ended, ongoing, plenty, scarce, unlimited, full)
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
                day_start=hour_of(ended),
                hours=[
                    ScheduleHour(start=hour_of(ended), sessions=[cards[ended.pk]]),
                    ScheduleHour(start=hour_of(ongoing), sessions=[cards[ongoing.pk]]),
                ],
                tiles=[tile(ended), tile(ongoing)],
            ),
            ScheduleDay(
                day_start=hour_of(plenty),
                hours=[
                    ScheduleHour(
                        start=hour_of(plenty),
                        sessions=[cards[plenty.pk], cards[scarce.pk]],
                    ),
                    ScheduleHour(
                        start=hour_of(unlimited), sessions=[cards[unlimited.pk]]
                    ),
                ],
                tiles=[tile(plenty), tile(scarce), tile(unlimited)],
            ),
            ScheduleDay(
                day_start=hour_of(full),
                hours=[ScheduleHour(start=hour_of(full), sessions=[cards[full.pk]])],
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
                filterable_tag_categories=[game_type],
                schedule_days=expected_days,
                # 4 seats in `scarce` plus the 2 that fill `full`.
                total_enrolled=4 + 2,
                hour_data={
                    ended.agenda_item.start_time: [cards[ended.pk]],
                    ongoing.agenda_item.start_time: [cards[ongoing.pk]],
                    plenty.agenda_item.start_time: [cards[plenty.pk], cards[scarce.pk]],
                    unlimited.agenda_item.start_time: [cards[unlimited.pk]],
                    full.agenda_item.start_time: [cards[full.pk]],
                },
            ),
            template_name=["chronology/event.html"],
        )
        content = response.content.decode()
        # The pills render inside their own spans; match with the tag boundary
        # so e.g. the "Enrollment Open" header pill can't satisfy "Open".
        for label in (
            "10 spots left",
            "1 spot left",
            "Open",
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
        assert_response(
            modal,
            HTTPStatus.OK,
            context_data=modal.context_data,
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
                                sessions=[cards[in_arena.pk], cards[on_stage.pk]],
                            ),
                            ScheduleHour(
                                start=local_start + timedelta(hours=2),
                                sessions=[cards[later_in_arena.pk]],
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
                schedule_view_is_list=False,
                schedule_view_is_rooms=True,
                room_lane_days=[
                    RoomLaneDay(
                        day_start=local_start,
                        rooms=["Arena", "Stage"],
                        # Four hours of lane, 10:00 to 13:00: the two sessions
                        # at 10:00, an empty 11:00, the two-hour one from
                        # 12:00, and the hour it runs into.
                        hour_marks=[
                            RoomLaneHourMark(
                                start=local_start, row=1, has_sessions=True
                            ),
                            RoomLaneHourMark(
                                start=local_start + timedelta(hours=1),
                                row=2,
                                has_sessions=False,
                            ),
                            RoomLaneHourMark(
                                start=local_start + timedelta(hours=2),
                                row=3,
                                has_sessions=True,
                            ),
                            RoomLaneHourMark(
                                start=local_start + timedelta(hours=3),
                                row=4,
                                has_sessions=False,
                            ),
                        ],
                        # Arena is column 1 and Stage column 2; the later
                        # session starts in the third row and spans two.
                        tiles=[
                            RoomLaneTile(
                                data=cards[in_arena.pk],
                                slot_hour=local_start,
                                col=1,
                                row_start=1,
                                row_span=1,
                            ),
                            RoomLaneTile(
                                data=cards[on_stage.pk],
                                slot_hour=local_start,
                                col=2,
                                row_start=1,
                                row_span=1,
                            ),
                            RoomLaneTile(
                                data=cards[later_in_arena.pk],
                                slot_hour=local_start + timedelta(hours=2),
                                col=1,
                                row_start=3,
                                row_span=2,
                            ),
                        ],
                    )
                ],
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        hour_start = timezone.localtime(agenda_item.start_time).replace(
            minute=0, second=0, microsecond=0
        )
        schedule_day = ScheduleDay(
            day_start=hour_start,
            hours=[ScheduleHour(start=hour_start, sessions=[session_data])],
            tiles=[
                ScheduleTile(
                    data=session_data,
                    start=timezone.localtime(agenda_item.start_time),
                    end=timezone.localtime(agenda_item.end_time),
                )
            ],
        )
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
            ),
            template_name=["chronology/event.html"],
            contains="session-grid",
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
        private_track = Track.objects.create(
            event=event, name="Backstage", slug="backstage", is_public=False
        )
        session_a = SessionFactory(event=event, category=category_a, min_age=0)
        session_a.tracks.add(track_a, private_track)
        session_b = SessionFactory(event=event, category=category_b, min_age=0)
        session_b.tracks.add(track_b)
        AgendaItemFactory(session=session_a, space=space)
        AgendaItemFactory(
            session=session_b,
            space=space,
            start_time=timezone.now() + timedelta(days=7, hours=3),
        )

        response = client.get(self._get_url(event.slug))

        content = response.content.decode()
        # Filter controls render (only when >1 value exists, so this also
        # proves has_track_filter / has_category_filter).
        assert 'data-category="__track"' in content
        assert 'data-category="__category"' in content
        # Cards carry the filter pairs; private tracks stay hidden.
        assert "__track:Main Hall" in content
        assert "__track:Side Room" in content
        assert "__category:RPG" in content
        assert "__category:Board games" in content
        assert "__track:Backstage" not in content

    def test_schedule_hides_sessions_whose_every_track_is_private(
        self, client, event, space
    ):
        public_track = Track.objects.create(
            event=event, name="Main Hall", slug="main", is_public=True
        )
        private_track = Track.objects.create(
            event=event, name="Backstage", slug="backstage", is_public=False
        )
        untracked = SessionFactory(event=event)
        mixed = SessionFactory(event=event)
        mixed.tracks.add(public_track, private_track)
        private_only = SessionFactory(event=event)
        private_only.tracks.add(private_track)
        for session in (untracked, mixed, private_only):
            AgendaItemFactory(session=session, space=space)

        response = client.get(self._get_url(event.slug))

        assert {card.session.pk for card in response.context_data["sessions"]} == {
            untracked.pk,
            mixed.pk,
        }

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

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["sessions"] == []

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
        assert event.cover_image_url.encode() in response.content

    @override_settings(MEDIA_URL="https://cdn.example.test/media/")
    def test_event_cover_image_used_as_absolute_social_metadata(self, client, event):
        event.cover_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        event.save()

        response = client.get(self._get_url(event.slug))

        content = response.content.decode()
        absolute_url = event.cover_image_url
        assert absolute_url.startswith("http")
        assert absolute_url in content
        assert "zagrajmy.net/static/logo.png" not in content
        assert f"testserver{absolute_url}" not in content

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
                filterable_tag_categories=[session_field],
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
            ),
            template_name=["chronology/event.html"],
            contains=["session-tags-more", "+1"],
        )

    def _add_scheduled_session(self, *, event, space, session_field):
        presenter = UserFactory()
        session = SessionFactory(
            presenter=presenter,
            display_name=presenter.name,
            event=event,
            participants_limit=10,
            min_age=0,
        )
        AgendaItemFactory(session=session, space=space)
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=["a", "b"]
        )
        SessionParticipation.objects.create(
            session=session,
            user=UserFactory(),
            status=SessionParticipationStatus.CONFIRMED,
        )
        session.refresh_from_db()
        return session

    @classmethod
    def _tagged_page_context(cls, event, *, url, sessions, session_field):
        cards = [
            cls._tagged_card(session, session_field=session_field)
            for session in sessions
        ]
        hour_data = {}
        for session, card in zip(sessions, cards, strict=True):
            hour_data.setdefault(session.agenda_item.start_time, []).append(card)
        return event_page_context(
            event,
            url=url,
            filterable_tag_categories=[session_field],
            has_category_filter=True,
            hour_data=hour_data,
            future_unavailable_hour_data=hour_data,
            sessions=cards,
            total_enrolled=len(cards),
        )

    @staticmethod
    def _tagged_card(session, *, session_field):
        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="",
            field_id=session_field.pk,
            field_name="Genre",
            field_question="Genre",
            field_slug="genre",
            field_type="select",
            is_public=True,
            value=["a", "b"],
        )
        return session_card(
            session.agenda_item,
            presenter=session.presenter,
            enrolled_count=1,
            full_participant_info="1/10",
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            ),
            template_name=["chronology/event.html"],
            contains=placeholder_cover_url(session.pk),
        )

    def test_ok_superuser_proposal(
        self, authenticated_client, event, active_user, pending_session
    ):
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        response = authenticated_client.get(self._get_url(event.slug))

        expected_pending = PendingSessionDTO(
            contact_email=pending_session.contact_email,
            creation_time=pending_session.creation_time,
            description=pending_session.description,
            participants_limit=pending_session.participants_limit,
            pk=pending_session.pk,
            display_name=pending_session.display_name,
            time_slots=[],
            title=pending_session.title,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._get_url(event.slug),
                pending_sessions=[expected_pending],
                pending_review_visible=True,
                pending_wizard_view=True,
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_superuser_pending_proposals_rendered(
        self, authenticated_client, event, active_user, pending_session
    ):
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        for offset in (0, 2, 4):
            pending_session.time_slots.add(
                TimeSlotFactory(
                    event=event, start_time=event.start_time + timedelta(hours=offset)
                )
            )
        flexible_session = SessionFactory(
            category=pending_session.category,
            presenter=active_user,
            display_name=active_user.name,
            participants_limit=5,
            min_age=0,
            status="pending",
        )

        response = authenticated_client.get(self._get_url(event.slug))

        expected_flexible = PendingSessionDTO(
            contact_email=flexible_session.contact_email,
            creation_time=flexible_session.creation_time,
            description=flexible_session.description,
            participants_limit=flexible_session.participants_limit,
            pk=flexible_session.pk,
            display_name=flexible_session.display_name,
            time_slots=[],
            title=flexible_session.title,
        )
        expected_pending = PendingSessionDTO(
            contact_email=pending_session.contact_email,
            creation_time=pending_session.creation_time,
            description=pending_session.description,
            participants_limit=pending_session.participants_limit,
            pk=pending_session.pk,
            display_name=pending_session.display_name,
            time_slots=[
                PendingSessionTimeSlotDTO.model_validate(ts)
                for ts in pending_session.time_slots.all()
            ],
            title=pending_session.title,
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
            contains=["Pending Proposals", "+1 more", "Flexible", "🧙"],
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

        expected_pending = PendingSessionDTO(
            contact_email=pending_session.contact_email,
            creation_time=pending_session.creation_time,
            description=pending_session.description,
            participants_limit=pending_session.participants_limit,
            pk=pending_session.pk,
            display_name=pending_session.display_name,
            time_slots=[],
            title=pending_session.title,
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
            contains="Pending Proposals",
            not_contains="🧙",
        )

    def test_ok_manager_sees_pending_proposals_without_wizard_emoji(
        self, authenticated_client, event, active_user, pending_session
    ):
        event.sphere.managers.add(active_user)
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])

        response = authenticated_client.get(self._get_url(event.slug))

        expected_pending = PendingSessionDTO(
            contact_email=pending_session.contact_email,
            creation_time=pending_session.creation_time,
            description=pending_session.description,
            participants_limit=pending_session.participants_limit,
            pk=pending_session.pk,
            display_name=pending_session.display_name,
            time_slots=[],
            title=pending_session.title,
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
            contains=["Pending Proposals", "Review & accept"],
            not_contains="🧙",
        )

    def test_ok_proposal_author_sees_own_proposal_card(
        self, authenticated_client, event, active_user, pending_session
    ):
        event.proposal_end_time = timezone.now() + timedelta(days=3)
        event.save(update_fields=["proposal_end_time"])
        assert pending_session.presenter == active_user

        response = authenticated_client.get(self._get_url(event.slug))

        expected_card = SessionData(
            agenda_item=None,
            is_enrollment_available=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session=SessionDTO.model_validate(pending_session),
            is_full=False,
            full_participant_info="0/10",
            effective_participants_limit=10,
            enrolled_count=0,
            session_participations=[],
            loc=LocationData(space_name="", parent_slug="", parent_name="", path=""),
            can_edit=True,
            category_name=pending_session.category.name,
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
            contains=[
                "Your pending proposals",
                pending_session.title,
                "Awaiting review",
            ],
            not_contains=["Pending Proposals", "Review & accept"],
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
            full_participant_info="1/10, 1 waiting",
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
            loc=LocationData(
                space_name=session.agenda_item.space.name,
                parent_slug=(
                    session.agenda_item.space.parent.slug
                    if session.agenda_item.space.parent
                    else ""
                ),
                parent_name=(
                    session.agenda_item.space.parent.name
                    if session.agenda_item.space.parent
                    else ""
                ),
                path=str(session.agenda_item.space),
            ),
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
                pending_review_visible=True,
                pending_wizard_view=True,
                sessions=[session_data],
                total_enrolled=1,
                user_enrolled_sessions=[session_data],
                user_enrolled_session_titles=[session_data.session.title],
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=host,
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            ),
            template_name=["chronology/event.html"],
        )

    def test_ok_unlimited_session(
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
            full_participant_info="0",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=host,
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="0/10",
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
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="0/10",
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
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="1/10",
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
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=True,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    allowed_slots=7 + 8, has_domain_config=False, has_user_config=True
                ),
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
        settings,
    ):
        slots = 7
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    allowed_slots=slots, has_domain_config=False, has_user_config=True
                ),
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
        settings,
    ):
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    allowed_slots=slots, has_domain_config=True, has_user_config=False
                ),
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    has_domain_config=True,
                    has_user_config=True,
                ),
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
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-10d", "-5d"),
        )
        slots = 7
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    allowed_slots=slots, has_domain_config=False, has_user_config=True
                ),
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
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    allowed_slots=0, has_domain_config=False, has_user_config=True
                ),
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
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-10d", "-5d"),
        )
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    allowed_slots=0, has_domain_config=False, has_user_config=True
                ),
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
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
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
            full_participant_info="0/10",
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                    allowed_slots=0, has_domain_config=False, has_user_config=True
                ),
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
                filterable_tag_categories=[session_field],
                future_unavailable_hour_data={agenda_item.start_time: [session_data]},
                hour_data={agenda_item.start_time: [session_data]},
                sessions=[session_data],
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
                filterable_tag_categories=[session_field],
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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
            full_participant_info="0/10",
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space_name=agenda_item.space.name,
                parent_slug=(
                    agenda_item.space.parent.slug if agenda_item.space.parent else ""
                ),
                parent_name=(
                    agenda_item.space.parent.name if agenda_item.space.parent else ""
                ),
                path=str(agenda_item.space),
            ),
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

    def test_owner_sees_edit_affordance(
        self, authenticated_client, event, active_user, space
    ):
        session = self._scheduled_session(event, active_user)
        AgendaItemFactory(session=session, space=space)
        edit_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event.slug, "session_id": session.pk},
        )

        response = authenticated_client.get(self._get_url(event.slug))

        session_data = next(
            s for s in response.context["sessions"] if s.session.pk == session.pk
        )
        assert session_data.can_edit is True
        # The edit button lives in the lazy-loaded session modal, not the page.
        modal = authenticated_client.get(
            reverse(
                "web:chronology:session-modal",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            )
        )
        assert_response(
            modal,
            HTTPStatus.OK,
            context_data=modal.context_data,
            template_name="chronology/parts/session-modal.html",
            contains=[edit_url, f'data-edit-open="{session.pk}"'],
        )

    def test_non_owner_no_edit_affordance(self, authenticated_client, event, space):
        other = UserFactory(username="other", email="other@example.com")
        session = self._scheduled_session(event, other)
        AgendaItemFactory(session=session, space=space)
        edit_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event.slug, "session_id": session.pk},
        )

        response = authenticated_client.get(self._get_url(event.slug))

        session_data = next(
            s for s in response.context["sessions"] if s.session.pk == session.pk
        )
        assert session_data.can_edit is False
        content = response.content.decode()
        assert edit_url not in content
        assert f'data-edit-open="{session.pk}"' not in content

    def test_owner_no_affordance_when_opted_out(
        self, authenticated_client, event, active_user, space
    ):
        event.allow_facilitator_session_edit = False
        event.save()
        session = self._scheduled_session(event, active_user)
        AgendaItemFactory(session=session, space=space)
        edit_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event.slug, "session_id": session.pk},
        )

        response = authenticated_client.get(self._get_url(event.slug))

        session_data = next(
            s for s in response.context["sessions"] if s.session.pk == session.pk
        )
        assert session_data.can_edit is False
        content = response.content.decode()
        assert edit_url not in content
        assert f'data-edit-open="{session.pk}"' not in content


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
