from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.adapters.web.django.views import EVENT_PLACEHOLDER_IMAGES, EventInfo
from ludamus.pacts import EventListItemDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    AreaFactory,
    EventFactory,
    SpaceFactory,
    VenueFactory,
)
from tests.integration.utils import assert_response

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _expected_event_info(event, *, session_count=0, cover_index=0):
    item = EventListItemDTO(
        description=event.description,
        end_time=event.end_time,
        is_ended=event.is_ended,
        is_live=event.is_live,
        is_proposal_active=event.is_proposal_active,
        is_published=event.is_published,
        name=event.name,
        session_count=session_count,
        slug=event.slug,
        start_time=event.start_time,
    )
    return EventInfo.from_list_item(
        item,
        cover_image_url=staticfiles_storage.url(EVENT_PLACEHOLDER_IMAGES[cover_index]),
    )


class TestIndexRedirectView:
    URL = reverse("web:index")

    def test_redirects_to_events_by_default(self, client):
        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:events"))

    def test_redirects_to_encounters_when_default_page_is_encounters(
        self, client, sphere
    ):
        sphere.default_page = "encounters"
        sphere.save()

        response = client.get(self.URL)

        assert_response(
            response, HTTPStatus.FOUND, url=reverse("web:notice-board:index")
        )


class TestEventsPageView:
    URL = reverse("web:events")

    def test_ok(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"past_events": [], "upcoming_events": [], "view": ANY},
            template_name=["index.html"],
        )

    def test_ok_with_event(self, client, event):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [_expected_event_info(event)],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_session_count_counts_agenda_items(self, client, sphere):
        event = EventFactory(sphere=sphere)
        space = SpaceFactory(area=AreaFactory(venue=VenueFactory(event=event)))
        AgendaItemFactory(space=space)
        AgendaItemFactory(space=space)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [_expected_event_info(event, session_count=2)],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_ok_with_event_cover_image(self, client, event):
        event.cover_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        event.save()

        response = client.get(self.URL)

        expected = _expected_event_info(event).model_copy(
            update={"cover_image_url": event.cover_image_url}
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [expected],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_ok_with_same_day_event(self, client, sphere, faker):
        """Cover line 17 in date_tags.py: same-day formatting."""
        day = faker.date_time_between(start_date="+7d", end_date="+30d", tzinfo=UTC)
        start = day.replace(hour=10, minute=0, second=0, microsecond=0)
        end = day.replace(hour=18, minute=0, second=0, microsecond=0)
        event = EventFactory(sphere=sphere, start_time=start, end_time=end)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [_expected_event_info(event)],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_ok_with_multi_month_event(self, client, sphere, faker):
        """Cover lines 31-41 in date_tags.py: different months, same year."""
        base = faker.date_time_between("+1y")
        start = datetime(base.year, 3, 15, 10, 0, tzinfo=UTC)
        end = datetime(base.year, 4, 20, 18, 0, tzinfo=UTC)
        event = EventFactory(sphere=sphere, start_time=start, end_time=end)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [_expected_event_info(event)],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_ok_with_multi_year_event(self, client, sphere):
        """Cover lines 42-47 in date_tags.py: different years."""
        now = datetime.now(UTC)
        start = datetime(now.year + 1, 12, 28, 10, 0, tzinfo=UTC)
        end = datetime(now.year + 2, 1, 3, 18, 0, tzinfo=UTC)
        event = EventFactory(sphere=sphere, start_time=start, end_time=end)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [_expected_event_info(event)],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_upcoming_events_sorted_soonest_first(self, client, sphere):
        now = datetime.now(UTC)
        far = EventFactory(
            sphere=sphere,
            start_time=now + timedelta(days=30),
            end_time=now + timedelta(days=31),
        )
        soon = EventFactory(
            sphere=sphere,
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [
                    _expected_event_info(soon, cover_index=0),
                    _expected_event_info(far, cover_index=1),
                ],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_past_events_sorted_most_recent_first(self, client, sphere):
        now = datetime.now(UTC)
        older = EventFactory(
            sphere=sphere,
            start_time=now - timedelta(days=30),
            end_time=now - timedelta(days=29),
            publication_time=now - timedelta(days=31),
        )
        recent = EventFactory(
            sphere=sphere,
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=2),
            publication_time=now - timedelta(days=4),
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [
                    _expected_event_info(recent, cover_index=1),
                    _expected_event_info(older, cover_index=0),
                ],
                "upcoming_events": [],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_panel_link_shown_for_sphere_manager(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.URL)

        assert response.status_code == HTTPStatus.OK
        assert "is_sphere_manager" in response.context
        assert response.context["is_sphere_manager"] is True
        assert b"Panel" in response.content

    def test_panel_link_hidden_for_non_manager(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert response.status_code == HTTPStatus.OK
        assert response.context["is_sphere_manager"] is False
        assert b'href="/panel/"' not in response.content

    def test_unpublished_event_hidden_for_anonymous(self, client, sphere):
        EventFactory(sphere=sphere, publication_time=None)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"past_events": [], "upcoming_events": [], "view": ANY},
            template_name=["index.html"],
        )

    def test_unpublished_event_hidden_for_regular_user(
        self, authenticated_client, sphere
    ):
        EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"past_events": [], "upcoming_events": [], "view": ANY},
            template_name=["index.html"],
        )

    def test_unpublished_event_visible_for_manager(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        event = EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "past_events": [],
                "upcoming_events": [_expected_event_info(event)],
                "view": ANY,
            },
            template_name=["index.html"],
        )
