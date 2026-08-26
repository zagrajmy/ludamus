from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse

from ludamus.gates.web.django.chronology.event_presentation import EventInfo
from ludamus.gates.web.django.helpers import placeholder_cover_url
from ludamus.gates.web.django.timeline import TimelineEncounter, TimelineEvent
from ludamus.pacts import EncounterDTO, EncounterIndexItem, EventListItemDTO
from tests.integration.conftest import EncounterFactory, EventFactory, UserFactory
from tests.integration.utils import assert_response, assert_response_404


def _event_info(event, *, cover_index=0):
    return EventInfo.from_list_item(
        EventListItemDTO(
            description=event.description,
            end_time=event.end_time,
            is_ended=event.is_ended,
            is_live=event.is_live,
            is_proposal_active=event.is_proposal_active,
            is_published=event.is_published,
            name=event.name,
            session_count=0,
            slug=event.slug,
            start_time=event.start_time,
        ),
        cover_image_url=placeholder_cover_url(cover_index),
    )


def _event_item(event, *, cover_index=0):
    return TimelineEvent(
        start_time=event.start_time, event=_event_info(event, cover_index=cover_index)
    )


def _encounter_item(encounter, *, organizer_name):
    return TimelineEncounter(
        start_time=encounter.start_time,
        encounter=EncounterIndexItem(
            encounter=EncounterDTO.model_validate(encounter),
            rsvp_count=0,
            is_mine=False,
            organizer_name=organizer_name,
        ),
    )


class TestTimelinePageView:
    URL = reverse("web:timeline")

    def test_ok_empty(self, client, sphere):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"timeline_upcoming": [], "timeline_past": [], "view": ANY},
            template_name=["timeline.html"],
        )

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
                "timeline_upcoming": [
                    _encounter_item(encounter, organizer_name="Pub Organizer"),
                    _event_item(event),
                ],
                "timeline_past": [],
                "view": ANY,
            },
            template_name=["timeline.html"],
        )

    def test_excludes_private_encounters_and_unpublished_events(self, client, sphere):
        now = datetime.now(UTC)
        EventFactory(sphere=sphere, publication_time=None)
        EncounterFactory(
            sphere=sphere, is_public=False, start_time=now + timedelta(days=2)
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"timeline_upcoming": [], "timeline_past": [], "view": ANY},
            template_name=["timeline.html"],
        )

    def test_past_events_listed_separately(self, client, sphere):
        now = datetime.now(UTC)
        past_event = EventFactory(
            sphere=sphere,
            start_time=now - timedelta(days=5),
            end_time=now - timedelta(days=4),
            publication_time=now - timedelta(days=6),
        )

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "timeline_upcoming": [],
                "timeline_past": [_event_info(past_event)],
                "view": ANY,
            },
            template_name=["timeline.html"],
        )

    def test_404_when_timeline_page_disabled(self, client, sphere):
        sphere.enabled_pages = ["events", "encounters"]
        sphere.save()

        response = client.get(self.URL)

        assert_response_404(response)
