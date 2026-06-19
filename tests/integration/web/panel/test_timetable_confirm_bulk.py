import json
from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Track
from tests.integration.conftest import (
    AgendaItemFactory,
    AreaFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    VenueFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _scheduled_agenda_item(sphere, event, area, *, track=None):
    space = SpaceFactory(area=area)
    session = SessionFactory(
        category=ProposalCategoryFactory(event=event),
        sphere=sphere,
        status="scheduled",
        participants_limit=5,
        min_age=0,
    )
    if track is not None:
        session.tracks.add(track)
    return AgendaItemFactory(
        session=session,
        space=space,
        start_time=event.start_time,
        end_time=event.start_time + timedelta(hours=1),
    )


class TestTimetableConfirmAllView:
    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-confirm-all", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_confirms_every_item_in_event(
        self, authenticated_client, active_user, sphere, event, area
    ):
        sphere.managers.add(active_user)
        item_a = _scheduled_agenda_item(sphere, event, area)
        item_b = _scheduled_agenda_item(sphere, event, area)

        response = authenticated_client.post(self.get_url(event))

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        item_a.refresh_from_db()
        item_b.refresh_from_db()
        assert item_a.session_confirmed is True
        assert item_b.session_confirmed is True

    def test_does_not_touch_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        other_area = AreaFactory(venue=VenueFactory(event=other_event))
        other_item = _scheduled_agenda_item(sphere, other_event, other_area)

        response = authenticated_client.post(self.get_url(event))

        assert_response(response, HTTPStatus.NO_CONTENT)
        other_item.refresh_from_db()
        assert other_item.session_confirmed is False

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirm-all", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )


class TestTimetableConfirmBlockView:
    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-confirm-block", kwargs={"slug": event.slug})

    @staticmethod
    def _track(event, slug="block-1"):
        return Track.objects.create(
            event=event, name="Block 1", slug=slug, is_public=True
        )

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={"track_pk": 1})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_missing_track_pk_returns_422(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), data={})

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_confirms_only_items_in_block(
        self, authenticated_client, active_user, sphere, event, area
    ):
        sphere.managers.add(active_user)
        track = self._track(event)
        in_block = _scheduled_agenda_item(sphere, event, area, track=track)
        out_of_block = _scheduled_agenda_item(sphere, event, area)

        response = authenticated_client.post(
            self.get_url(event), data={"track_pk": track.pk}
        )

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        in_block.refresh_from_db()
        out_of_block.refresh_from_db()
        assert in_block.session_confirmed is True
        assert out_of_block.session_confirmed is False

    def test_returns_422_for_track_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        other_track = self._track(other_event, slug="other-block")
        other_area = AreaFactory(venue=VenueFactory(event=other_event))
        other_item = _scheduled_agenda_item(
            sphere, other_event, other_area, track=other_track
        )

        response = authenticated_client.post(
            self.get_url(event), data={"track_pk": other_track.pk}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_item.refresh_from_db()
        assert other_item.session_confirmed is False

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirm-block", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={"track_pk": 1})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
