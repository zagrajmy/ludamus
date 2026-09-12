from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.gates.web.django.chronology.event_presentation import EventInfo
from ludamus.gates.web.django.events import FeedEncounter, FeedEvent
from ludamus.gates.web.django.helpers import placeholder_cover_url
from ludamus.links.db.django.models import Announcement, Track
from ludamus.pacts import EncounterDTO, EncounterIndexItem, EventListItemDTO
from ludamus.pacts.encounter import PAST_FEED_LIMIT
from ludamus.pacts.multiverse import AnnouncementDTO
from tests.integration.conftest import (
    PNG_BYTES,
    AgendaItemFactory,
    EncounterFactory,
    EncounterRSVPFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import assert_response


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
        item, cover_image_url=placeholder_cover_url(cover_index)
    )


def _expected_feed_event(event, **kwargs):
    return FeedEvent(entry=_expected_event_info(event, **kwargs))


class TestIndexRedirectView:
    URL = reverse("web:index")

    def test_redirects_to_events(self, client):
        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:events"))


class TestEventsPageView:
    URL = reverse("web:events")

    def test_ok(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
            cache_control={"private", "max-age=180"},
        )
        assert "Cookie" in response.headers.get("Vary", "")
        assert f'data-commit-sha="{settings.COMMIT_SHA}"'.encode() in response.content

    def test_ok_with_event(self, client, event):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [_expected_feed_event(event)],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_session_count_counts_scheduled_sessions(self, client, sphere):
        event = EventFactory(sphere=sphere)
        space = SpaceFactory(event=event)
        AgendaItemFactory(space=space, session=SessionFactory(category__event=event))
        AgendaItemFactory(space=space, session=SessionFactory(category__event=event))
        SessionFactory(category__event=event)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [_expected_feed_event(event, session_count=2)],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_session_count_matches_public_schedule(self, client, sphere):
        event = EventFactory(sphere=sphere)
        space = SpaceFactory(event=event)
        public_track = Track.objects.create(
            event=event, name="Main Hall", slug="main", is_public=True
        )
        private_track = Track.objects.create(
            event=event, name="Backstage", slug="backstage", is_public=False
        )
        untracked = SessionFactory(category__event=event)
        public_only = SessionFactory(category__event=event)
        public_only.tracks.add(public_track)
        mixed = SessionFactory(category__event=event)
        mixed.tracks.add(public_track, private_track)
        private_only = SessionFactory(category__event=event)
        private_only.tracks.add(private_track)
        deleted = SessionFactory(category__event=event)
        for session in (untracked, public_only, mixed, private_only, deleted):
            AgendaItemFactory(space=space, session=session)
        deleted.soft_delete()

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [_expected_feed_event(event, session_count=2)],
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
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [FeedEvent(entry=expected)],
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
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [_expected_feed_event(event)],
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
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [_expected_feed_event(event)],
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
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [_expected_feed_event(event)],
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
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [
                    _expected_feed_event(soon, cover_index=0),
                    _expected_feed_event(far, cover_index=1),
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
                "announcements": [],
                "can_create_encounter": False,
                "past": [
                    _expected_feed_event(recent, cover_index=0),
                    _expected_feed_event(older, cover_index=1),
                ],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_mixed_buckets_each_sorted_independently(self, client, sphere):
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
        recent = EventFactory(
            sphere=sphere,
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=2),
            publication_time=now - timedelta(days=4),
        )
        older = EventFactory(
            sphere=sphere,
            start_time=now - timedelta(days=30),
            end_time=now - timedelta(days=29),
            publication_time=now - timedelta(days=31),
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "upcoming": [
                    _expected_feed_event(soon, cover_index=0),
                    _expected_feed_event(far, cover_index=1),
                ],
                "past": [
                    _expected_feed_event(recent, cover_index=0),
                    _expected_feed_event(older, cover_index=1),
                ],
                "announcements": [],
                "can_create_encounter": False,
                "view": ANY,
            },
            template_name=["index.html"],
        )

    @pytest.mark.usefixtures("panel_access_user")
    def test_panel_link_shown_for_manager_and_superuser(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": True,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
            contains='href="/panel/"',
        )

    def test_panel_link_hidden_for_non_manager(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": True,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
            not_contains='href="/panel/"',
        )

    def test_published_announcement_shown(self, client, sphere):
        announcement = Announcement.objects.create(
            sphere=sphere, title="Welcome", content="Hello there"
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [AnnouncementDTO.model_validate(announcement)],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
            contains=["Welcome", "Hello there"],
        )

    def test_draft_announcement_hidden(self, client, sphere):
        Announcement.objects.create(
            sphere=sphere, title="Secret", content="body", is_published=False
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
            not_contains="Secret",
        )

    def test_announcement_scoped_to_current_sphere(self, client, non_root_sphere):
        Announcement.objects.create(
            sphere=non_root_sphere, title="Elsewhere", content="body"
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_unpublished_event_hidden_for_anonymous(self, client, sphere):
        EventFactory(sphere=sphere, publication_time=None)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
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
            context_data={
                "announcements": [],
                "can_create_encounter": True,
                "past": [],
                "upcoming": [],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    @pytest.mark.usefixtures("panel_access_user")
    def test_unpublished_event_visible_for_manager_and_superuser(
        self, authenticated_client, sphere
    ):
        event = EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": True,
                "past": [],
                "upcoming": [_expected_feed_event(event)],
                "view": ANY,
            },
            template_name=["index.html"],
        )


def _feed_context(*, upcoming=(), past=(), can_create_encounter=False):
    return {
        "announcements": [],
        "can_create_encounter": can_create_encounter,
        "past": list(past),
        "upcoming": list(upcoming),
        "view": ANY,
    }


def _expected_feed_encounter(encounter, *, organizer_name, rsvp_count=0, is_mine=False):
    return FeedEncounter(
        entry=EncounterIndexItem(
            encounter=EncounterDTO.model_validate(encounter),
            rsvp_count=rsvp_count,
            is_mine=is_mine,
            organizer_name=organizer_name,
        )
    )


class TestEventsPageFeed:
    URL = reverse("web:events")

    def test_merges_events_and_public_encounters_chronologically(self, client, sphere):
        now = datetime.now(UTC)
        event = EventFactory(
            sphere=sphere,
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=6),
        )
        creator = UserFactory(username="pub_organizer", name="Pub Organizer")
        encounter = EncounterFactory(
            sphere=sphere,
            creator=creator,
            is_public=True,
            start_time=now + timedelta(days=2),
        )

        response = client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "can_create_encounter": False,
                "past": [],
                "upcoming": [
                    _expected_feed_encounter(encounter, organizer_name="Pub Organizer"),
                    _expected_feed_event(event),
                ],
                "view": ANY,
            },
            template_name=["index.html"],
        )

    def test_private_encounter_is_hidden_from_other_visitors(self, client, sphere):
        EncounterFactory(
            sphere=sphere,
            is_public=False,
            start_time=datetime.now(UTC) + timedelta(days=2),
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_feed_context(),
            template_name=["index.html"],
        )

    def test_private_encounter_is_hidden_from_an_uninvited_signed_in_visitor(
        self, authenticated_client, sphere
    ):
        EncounterFactory(
            sphere=sphere,
            creator=UserFactory(username="host", name="Host"),
            is_public=False,
            start_time=datetime.now(UTC) + timedelta(days=2),
        )

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_feed_context(can_create_encounter=True),
            template_name=["index.html"],
        )

    def test_own_private_encounter_is_listed_for_its_organizer(
        self, authenticated_client, sphere, active_user
    ):
        encounter = EncounterFactory(
            sphere=sphere,
            creator=active_user,
            is_public=False,
            start_time=datetime.now(UTC) + timedelta(days=2),
        )

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_feed_context(
                can_create_encounter=True,
                upcoming=[
                    _expected_feed_encounter(encounter, organizer_name="", is_mine=True)
                ],
            ),
            template_name=["index.html"],
        )

    def test_invited_encounter_is_listed_for_the_attendee(
        self, authenticated_client, sphere, active_user
    ):
        encounter = EncounterFactory(
            sphere=sphere,
            creator=UserFactory(username="host", name="Host"),
            is_public=False,
            start_time=datetime.now(UTC) + timedelta(days=2),
        )
        EncounterRSVPFactory(encounter=encounter, user=active_user)

        response = authenticated_client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_feed_context(
                can_create_encounter=True,
                upcoming=[
                    _expected_feed_encounter(
                        encounter, organizer_name="Host", rsvp_count=1
                    )
                ],
            ),
            template_name=["index.html"],
        )

    def test_past_encounters_join_past_events(self, client, sphere):
        now = datetime.now(UTC)
        past_event = EventFactory(
            sphere=sphere,
            start_time=now - timedelta(days=5),
            end_time=now - timedelta(days=4),
            publication_time=now - timedelta(days=6),
        )
        encounter = EncounterFactory(
            sphere=sphere,
            creator=UserFactory(username="host", name="Host"),
            is_public=True,
            start_time=now - timedelta(days=1),
            end_time=now - timedelta(hours=20),
        )

        response = client.get(self.URL)

        encounter.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_feed_context(
                past=[
                    _expected_feed_encounter(encounter, organizer_name="Host"),
                    _expected_feed_event(past_event),
                ]
            ),
            template_name=["index.html"],
        )

    def test_the_past_section_stops_at_one_cut_across_both_kinds(self, client, sphere):
        now = datetime.now(UTC)
        for days in range(1, PAST_FEED_LIMIT + 2):
            EncounterFactory(
                sphere=sphere,
                is_public=True,
                start_time=now - timedelta(days=days),
                end_time=now - timedelta(days=days) + timedelta(hours=1),
            )
        EventFactory(
            sphere=sphere,
            start_time=now - timedelta(days=365),
            end_time=now - timedelta(days=364),
            publication_time=now - timedelta(days=366),
        )

        response = client.get(self.URL)

        assert_response(
            response, HTTPStatus.OK, context_data=ANY, template_name=["index.html"]
        )
        past = response.context_data["past"]
        assert len(past) == PAST_FEED_LIMIT
        assert all(item.kind == "encounter" for item in past)

    def test_encounters_are_absent_while_the_sphere_runs_none(self, client, sphere):
        EncounterFactory(
            sphere=sphere,
            is_public=True,
            start_time=datetime.now(UTC) + timedelta(days=2),
        )
        sphere.encounters_policy = "none"
        sphere.save()

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_feed_context(),
            template_name=["index.html"],
        )
