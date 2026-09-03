from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from zeal import zeal_ignore

from ludamus.links.db.django.models import EventMap
from ludamus.pacts import EventDTO
from ludamus.pacts.maps import EventMapDTO, MapTreeNodeDTO
from tests.integration.conftest import PNG_BYTES, EventFactory, SpaceFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.chronology.helpers import event_page_context, session_card

PERMISSION_ERROR = "Only the event's organizers can change its maps."


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


def _png(name="plan.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


def _maps_url(event):
    return reverse("web:chronology:event-maps", kwargs={"slug": event.slug})


def _card(event_map, *, space_pks, tree):
    return EventMapDTO(
        pk=event_map.pk,
        event_id=event_map.event_id,
        name=event_map.name,
        image_url=event_map.image.url,
        image_original_name="plan.png",
        space_pks=space_pks,
        tree=tree,
    )


class CardsMatcher:
    # The page wraps each map DTO with two bound forms; the DTOs are the
    # comparable part, so equality reads them off whatever cards rendered.
    def __init__(self, maps):
        self.maps = maps

    def __eq__(self, other):
        return [card.map for card in other] == self.maps

    def __hash__(self):
        return hash(tuple(event_map.pk for event_map in self.maps))

    def __repr__(self):
        return f"CardsMatcher({self.maps!r})"


@pytest.fixture(name="organizer_client")
def organizer_client_fixture(authenticated_client, active_user, sphere):
    sphere.managers.add(active_user)
    return authenticated_client


@pytest.mark.django_db
class TestEventMapsPageView:
    def test_viewer_gets_every_map_with_its_venue_tree(self, client, event):
        # A room attached on its own still shows the venue it sits in, as a
        # plain (unlinked) ancestor; the venue attached itself links.
        hall = SpaceFactory(event=event, name="Hall")
        room = SpaceFactory(event=event, name="Room 1", parent=hall)
        site_plan = make_map(event, "Site plan", hall)
        floor_plan = make_map(event, "Ground floor", room)

        response = client.get(_maps_url(event))

        expected_maps = [
            _card(
                site_plan,
                space_pks=[hall.pk],
                tree=[
                    MapTreeNodeDTO(
                        pk=hall.pk,
                        name="Hall",
                        attached=True,
                        has_children=True,
                        schedule_filter=f"venue:{hall.pk}",
                        children=[],
                    )
                ],
            ),
            _card(
                floor_plan,
                space_pks=[room.pk],
                tree=[
                    MapTreeNodeDTO(
                        pk=hall.pk,
                        name="Hall",
                        attached=False,
                        has_children=True,
                        schedule_filter=f"venue:{hall.pk}",
                        children=[
                            MapTreeNodeDTO(
                                pk=room.pk,
                                name="Room 1",
                                attached=True,
                                has_children=False,
                                schedule_filter=str(room.pk),
                                children=[],
                            )
                        ],
                    )
                ],
            ),
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/maps.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "schedule_url": f"/event/{event.slug}/",
                "cards": CardsMatcher(expected_maps),
                "can_edit": False,
                "add_form": ANY,
            },
        )

    def test_organizer_gets_the_same_page_with_editing_on(
        self, organizer_client, event
    ):
        response = organizer_client.get(_maps_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/maps.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "schedule_url": f"/event/{event.slug}/",
                "cards": [],
                "can_edit": True,
                "add_form": ANY,
            },
        )

    def test_unknown_event_is_not_found(self, client):
        response = client.get(
            reverse("web:chronology:event-maps", kwargs={"slug": "nonexistent"})
        )

        assert_response_404(response)

    def test_unpublished_event_is_not_found_for_anonymous(self, client, event):
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()

        response = client.get(_maps_url(event))

        assert_response_404(response)


@pytest.mark.django_db
class TestEventMapAddActionView:
    @staticmethod
    def _url(event):
        return reverse("web:chronology:event-map-add", kwargs={"slug": event.slug})

    def test_viewer_is_refused_without_writing(self, authenticated_client, event):
        response = authenticated_client.post(
            self._url(event), data={"name": "Site plan", "image": _png()}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, PERMISSION_ERROR)],
        )
        assert not EventMap.objects.exists()

    def test_organizer_adds_a_map(self, organizer_client, event):
        response = organizer_client.post(
            self._url(event), data={"name": "Site plan", "image": _png()}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.SUCCESS, "Map added.")],
        )
        event_map = EventMap.objects.get()
        assert event_map.event_id == event.pk
        assert event_map.name == "Site plan"
        assert event_map.image_original_name == "plan.png"

    def test_missing_image_reopens_the_dialog_with_the_error(
        self, organizer_client, event
    ):
        response = organizer_client.post(self._url(event), data={"name": "Site plan"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/maps.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "schedule_url": f"/event/{event.slug}/",
                "cards": [],
                "can_edit": True,
                "add_form": ANY,
            },
        )
        add_form = response.context_data["add_form"]
        assert add_form.errors == {"image": ["Upload the map image."]}
        assert not EventMap.objects.exists()


@pytest.mark.django_db
class TestEventMapEditActionView:
    @staticmethod
    def _url(event, pk):
        return reverse(
            "web:chronology:event-map-edit", kwargs={"slug": event.slug, "pk": pk}
        )

    def test_viewer_is_refused_without_writing(self, authenticated_client, event):
        event_map = make_map(event, "Site plan")

        response = authenticated_client.post(
            self._url(event, event_map.pk), data={"name": "Hijacked"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, PERMISSION_ERROR)],
        )
        event_map.refresh_from_db()
        assert event_map.name == "Site plan"

    def test_blank_name_reopens_the_dialog_with_the_error(
        self, organizer_client, event
    ):
        event_map = make_map(event, "Site plan")

        response = organizer_client.post(
            self._url(event, event_map.pk), data={"name": "   "}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/maps.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "schedule_url": f"/event/{event.slug}/",
                "cards": CardsMatcher([_card(event_map, space_pks=[], tree=[])]),
                "can_edit": True,
                "add_form": ANY,
            },
        )
        edit_form = response.context_data["cards"][0].edit_form
        assert edit_form.errors == {"name": ["Map name is required."]}
        event_map.refresh_from_db()
        assert event_map.name == "Site plan"

    def test_rename_keeps_the_stored_image(self, organizer_client, event):
        event_map = make_map(event, "Site plan")
        stored = event_map.image.name

        response = organizer_client.post(
            self._url(event, event_map.pk), data={"name": "Renamed"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.SUCCESS, "Map saved.")],
        )
        event_map.refresh_from_db()
        assert event_map.name == "Renamed"
        assert event_map.image.name == stored

    def test_new_upload_replaces_the_image(self, organizer_client, event):
        event_map = make_map(event, "Site plan")
        stored = event_map.image.name

        response = organizer_client.post(
            self._url(event, event_map.pk),
            data={"name": "Site plan", "image": _png("new.png")},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.SUCCESS, "Map saved.")],
        )
        event_map.refresh_from_db()
        assert event_map.image.name != stored
        assert event_map.image_original_name == "new.png"

    def test_map_of_another_event_is_not_found(self, organizer_client, event):
        foreign = make_map(EventFactory(), "Elsewhere")

        response = organizer_client.post(
            self._url(event, foreign.pk), data={"name": "Hijacked"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.ERROR, "Map not found.")],
        )
        foreign.refresh_from_db()
        assert foreign.name == "Elsewhere"


@pytest.mark.django_db
class TestEventMapAttachActionView:
    @staticmethod
    def _url(event, pk):
        return reverse(
            "web:chronology:event-map-attach", kwargs={"slug": event.slug, "pk": pk}
        )

    def test_organizer_attaches_venues(self, organizer_client, event):
        room = SpaceFactory(event=event, name="Room 1")
        event_map = make_map(event, "Site plan")

        response = organizer_client.post(
            self._url(event, event_map.pk), data={"spaces": [str(room.pk)]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.SUCCESS, "Venues on the map updated.")],
        )
        assert list(event_map.spaces.all()) == [room]

    def test_space_of_another_event_is_not_a_choice(self, organizer_client, event):
        # The checklist is the event's own tree, so a foreign pk fails form
        # validation and the dialog reopens; nothing is written.
        foreign = SpaceFactory(event=EventFactory())
        event_map = make_map(event, "Site plan")

        response = organizer_client.post(
            self._url(event, event_map.pk), data={"spaces": [str(foreign.pk)]}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/maps.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "schedule_url": f"/event/{event.slug}/",
                "cards": CardsMatcher([_card(event_map, space_pks=[], tree=[])]),
                "can_edit": True,
                "add_form": ANY,
            },
        )
        assert not event_map.spaces.exists()

    def test_map_of_another_event_is_not_found(self, organizer_client, event):
        room = SpaceFactory(event=event, name="Room 1")
        foreign = make_map(EventFactory(), "Elsewhere")

        response = organizer_client.post(
            self._url(event, foreign.pk), data={"spaces": [str(room.pk)]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.ERROR, "Map not found.")],
        )
        assert not foreign.spaces.exists()

    def test_viewer_is_refused(self, authenticated_client, event):
        room = SpaceFactory(event=event, name="Room 1")
        event_map = make_map(event, "Site plan")

        response = authenticated_client.post(
            self._url(event, event_map.pk), data={"spaces": [str(room.pk)]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, PERMISSION_ERROR)],
        )
        assert not event_map.spaces.exists()


@pytest.mark.django_db
class TestEventMapDeleteActionView:
    @staticmethod
    def _url(event, pk):
        return reverse(
            "web:chronology:event-map-delete", kwargs={"slug": event.slug, "pk": pk}
        )

    def test_viewer_is_refused_without_deleting(self, authenticated_client, event):
        event_map = make_map(event, "Site plan")

        response = authenticated_client.post(self._url(event, event_map.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, PERMISSION_ERROR)],
        )
        assert EventMap.objects.filter(pk=event_map.pk).exists()

    def test_organizer_deletes_the_map(self, organizer_client, event):
        event_map = make_map(event, "Site plan")

        response = organizer_client.post(self._url(event, event_map.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.SUCCESS, "Map deleted.")],
        )
        assert not EventMap.objects.exists()

    def test_map_of_another_event_is_left_alone(self, organizer_client, event):
        foreign = make_map(EventFactory(), "Elsewhere")

        response = organizer_client.post(self._url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_maps_url(event),
            messages=[(messages.ERROR, "Map not found.")],
        )
        assert EventMap.objects.filter(pk=foreign.pk).exists()


@pytest.mark.django_db
class TestEventPageMapLinks:
    @staticmethod
    def _url(slug):
        return reverse("web:chronology:event", kwargs={"slug": slug})

    def test_hero_links_to_the_maps_page(self, client, event, agenda_item):
        building = SpaceFactory(event=event, name="Hall")
        agenda_item.space.parent = building
        agenda_item.space.save()
        make_map(event, "Site plan", building)
        url = self._url(event.slug)

        response = client.get(url)

        card = session_card(agenda_item, presenter=agenda_item.session.presenter)
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
