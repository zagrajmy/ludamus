from datetime import timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.gates.web.django.chronology.schedule import (
    RoomLaneDay,
    RoomLaneHourMark,
    RoomLaneTile,
)
from ludamus.links.db.django.models import SessionBookmark
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SphereFactory,
    UserFactory,
)
from tests.integration.utils import assert_response
from tests.integration.web.chronology.helpers import (
    compact_day,
    event_page_context,
    session_card,
)

BOOKMARK_COUNT = 3


class TestSessionBookmarkToggleView:
    URL_NAME = "web:chronology:session-bookmark"

    def _url(self, session_id: int) -> str:
        return reverse(self.URL_NAME, kwargs={"session_id": session_id})

    def test_unauthorized_when_anonymous(self, client, session):
        response = client.post(self._url(session.pk))

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"error": "auth"}
        assert not SessionBookmark.objects.exists()

    def test_toggle_on_then_off(self, authenticated_client, active_user, session):
        SessionBookmark.objects.create(user=UserFactory(), session=session)

        response_on = authenticated_client.post(self._url(session.pk))

        assert response_on.status_code == HTTPStatus.OK
        assert response_on.json() == {"bookmarked": True, "count": 2}
        bookmark = SessionBookmark.objects.get(user=active_user, session=session)
        assert str(bookmark) == f"{active_user.pk} bookmarked session {session.pk}"

        response_off = authenticated_client.post(self._url(session.pk))

        assert response_off.status_code == HTTPStatus.OK
        assert response_off.json() == {"bookmarked": False, "count": 1}
        assert not SessionBookmark.objects.filter(user=active_user).exists()

    def test_not_found_for_other_sphere_session(self, authenticated_client):
        other_event = EventFactory(sphere=SphereFactory())
        other_session = SessionFactory(event=other_event, category=None)

        response = authenticated_client.post(self._url(other_session.pk))

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"error": "not-found"}
        assert not SessionBookmark.objects.exists()

    @pytest.mark.usefixtures("session")
    def test_not_found_for_missing_session(self, authenticated_client):
        response = authenticated_client.post(self._url(999_999))

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"error": "not-found"}


class TestEventPageBookmarkCounts:
    URL_NAME = "web:chronology:event"

    def _url(self, slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    @pytest.fixture(autouse=True)
    def _compact_schedule(self, monkeypatch):
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )

    def test_anonymous_sees_count_badge_and_zero_count_renders_nothing(
        self, agenda_item, client, event, space
    ):
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        other = AgendaItemFactory(
            session=SessionFactory(event=event, category=None), space=space
        )

        response = client.get(self._url(event.slug))

        cards = [
            session_card(
                agenda_item, presenter=agenda_item.session.presenter, bookmark_count=2
            ),
            session_card(other, presenter=other.session.presenter),
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._url(event.slug),
                compact_schedule=True,
                hour_data={
                    agenda_item.start_time: [cards[0]],
                    other.start_time: [cards[1]],
                },
                schedule_days=[compact_day(cards)],
                sessions=cards,
            ),
            template_name=["chronology/event.html"],
            contains="Bookmarked by 2 people",
            not_contains=["bookmark-toggle", "Bookmarked by 0"],
        )

    def test_anonymous_rooms_view_shows_count_badge(self, agenda_item, client, event):
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        # Whole hours, so the lane's rows are the session's own two hours and
        # not a third one the fixture's sub-second offset would spill into.
        hour_start = localtime(agenda_item.start_time).replace(
            minute=0, second=0, microsecond=0
        )
        agenda_item.start_time = hour_start
        agenda_item.end_time = hour_start + timedelta(hours=2)
        agenda_item.save()

        response = client.get(self._url(event.slug), {"view": "rooms"})

        card = session_card(
            agenda_item, presenter=agenda_item.session.presenter, bookmark_count=1
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._url(event.slug),
                compact_schedule=True,
                hour_data={agenda_item.start_time: [card]},
                schedule_days=[compact_day([card])],
                schedule_view_is_list=False,
                schedule_view_is_rooms=True,
                room_lane_days=[
                    RoomLaneDay(
                        day_start=hour_start,
                        rooms=[agenda_item.space.name],
                        hour_marks=[
                            RoomLaneHourMark(
                                start=hour_start, row=1, has_sessions=True
                            ),
                            RoomLaneHourMark(
                                start=hour_start + timedelta(hours=1),
                                row=2,
                                has_sessions=False,
                            ),
                        ],
                        tiles=[
                            RoomLaneTile(
                                data=card,
                                slot_hour=hour_start,
                                col=1,
                                row_start=1,
                                row_span=2,
                            )
                        ],
                    )
                ],
                sessions=[card],
            ),
            template_name=["chronology/event.html"],
            contains="Bookmarked by 1 person",
        )

    def test_authenticated_toggle_shows_count_and_hides_zero(
        self, agenda_item, authenticated_client, event, space
    ):
        for _ in range(BOOKMARK_COUNT):
            SessionBookmark.objects.create(
                user=UserFactory(), session=agenda_item.session
            )
        other = AgendaItemFactory(
            session=SessionFactory(event=event, category=None), space=space
        )

        response = authenticated_client.get(self._url(event.slug))

        cards = [
            session_card(
                agenda_item,
                presenter=agenda_item.session.presenter,
                bookmark_count=BOOKMARK_COUNT,
                # The viewer hosts this one, so its card offers the edit link.
                can_edit=True,
            ),
            session_card(other, presenter=other.session.presenter),
        ]
        # The class strings are the .bookmark-count contract with
        # session-bookmarks.ts: a visible "3" on the bookmarked session and a
        # hidden "0" inside the other session's toggle button.
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=self._url(event.slug),
                compact_schedule=True,
                hour_data={
                    agenda_item.start_time: [cards[0]],
                    other.start_time: [cards[1]],
                },
                schedule_days=[compact_day(cards)],
                sessions=cards,
            ),
            template_name=["chronology/event.html"],
            contains=['tabular-nums ">3</span>', 'tabular-nums hidden">0</span>'],
        )
