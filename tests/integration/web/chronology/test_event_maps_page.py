from datetime import timedelta
from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from zeal import zeal_ignore

from ludamus.links.db.django.models import EventMap
from ludamus.pacts import EventDTO
from ludamus.pacts.maps import EventMapDTO, MapSpaceDTO
from tests.integration.conftest import PNG_BYTES, SpaceFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.chronology.helpers import event_page_context, session_card


def make_map(event, name, *spaces):
    event_map = EventMap.objects.create(
        event=event,
        name=name,
        image=SimpleUploadedFile("plan.png", PNG_BYTES, content_type="image/png"),
        image_original_name="plan.png",
    )
    # Fixture setup, not the code under test: each helper call writes one
    # map's spaces, which zeal reads as the same relation loaded in a loop.
    with zeal_ignore():
        event_map.spaces.set(spaces)
    return event_map


@pytest.mark.django_db
class TestEventMapsPageView:
    @staticmethod
    def _url(slug):
        return reverse("web:chronology:event-maps", kwargs={"slug": slug})

    def test_lists_every_map_with_its_venues(self, client, event):
        building = SpaceFactory(event=event, name="Hall")
        room = SpaceFactory(event=event, name="Room 1", parent=building)
        site_plan = make_map(event, "Site plan", building)
        floor_plan = make_map(event, "Ground floor", room)

        response = client.get(self._url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/maps.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "schedule_url": f"/event/{event.slug}/",
                "maps": [
                    EventMapDTO(
                        pk=site_plan.pk,
                        event_id=event.pk,
                        name="Site plan",
                        image_url=site_plan.image.url,
                        image_original_name="plan.png",
                        spaces=[
                            MapSpaceDTO(pk=building.pk, name="Hall", has_children=True)
                        ],
                    ),
                    EventMapDTO(
                        pk=floor_plan.pk,
                        event_id=event.pk,
                        name="Ground floor",
                        image_url=floor_plan.image.url,
                        image_original_name="plan.png",
                        spaces=[
                            MapSpaceDTO(
                                pk=room.pk, name="Hall > Room 1", has_children=False
                            )
                        ],
                    ),
                ],
            },
        )

    def test_event_without_maps_renders_the_empty_state(self, client, event):
        response = client.get(self._url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/maps.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "schedule_url": f"/event/{event.slug}/",
                "maps": [],
            },
        )

    def test_unknown_event_is_not_found(self, client):
        response = client.get(self._url("nonexistent"))

        assert_response_404(response)

    def test_unpublished_event_is_not_found_for_anonymous(self, client, event):
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()

        response = client.get(self._url(event.slug))

        assert_response_404(response)


@pytest.mark.django_db
class TestEventPageMapLinks:
    @staticmethod
    def _url(slug):
        return reverse("web:chronology:event", kwargs={"slug": slug})

    def test_hero_links_to_the_maps_page_and_cards_to_their_map(
        self, client, event, agenda_item
    ):
        # The room is not on the map, its venue is: the card still finds it.
        building = SpaceFactory(event=event, name="Hall")
        agenda_item.space.parent = building
        agenda_item.space.save()
        site_plan = make_map(event, "Site plan", building)
        url = self._url(event.slug)

        response = client.get(url)

        card = session_card(
            agenda_item, presenter=agenda_item.session.presenter, map_pk=site_plan.pk
        )
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["chronology/event.html"],
            context_data=event_page_context(
                event,
                url=url,
                hour_data={agenda_item.start_time: [card]},
                future_unavailable_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
                maps_url=f"/event/{event.slug}/maps/",
            ),
        )
