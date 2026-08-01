import json
from datetime import timedelta
from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import Track
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
)


def _scheduled_agenda_item(event, *, track=None):
    space = SpaceFactory(event=event)
    session = SessionFactory(
        category=ProposalCategoryFactory(event=event),
        status="accepted",
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

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event))

        assert_not_a_manager(response)

    def test_confirms_every_item_in_event(self, panel_client, event):
        item_a = _scheduled_agenda_item(event)
        item_b = _scheduled_agenda_item(event)

        response = panel_client.post(self.get_url(event))

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        item_a.refresh_from_db()
        item_b.refresh_from_db()
        assert item_a.session_confirmed is True
        assert item_b.session_confirmed is True

    def test_does_not_touch_other_event(self, panel_client, sphere, event):
        other_event = EventFactory(sphere=sphere)
        other_item = _scheduled_agenda_item(other_event)

        response = panel_client.post(self.get_url(event))

        assert_response(response, HTTPStatus.NO_CONTENT)
        other_item.refresh_from_db()
        assert other_item.session_confirmed is False

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-confirm-all", kwargs={"slug": "nonexistent"})

        response = panel_client.post(url)

        assert_event_not_found(response)


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

        assert_login_required(response, url)

    def test_missing_track_pk_returns_422(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={})

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_confirms_only_items_in_block(self, panel_client, event):
        track = self._track(event)
        in_block = _scheduled_agenda_item(event, track=track)
        out_of_block = _scheduled_agenda_item(event)

        response = panel_client.post(self.get_url(event), data={"track_pk": track.pk})

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert json.loads(response.headers["HX-Trigger"]) == {"timetableChanged": {}}
        in_block.refresh_from_db()
        out_of_block.refresh_from_db()
        assert in_block.session_confirmed is True
        assert out_of_block.session_confirmed is False

    def test_returns_422_for_track_from_another_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        other_track = self._track(other_event, slug="other-block")
        other_item = _scheduled_agenda_item(other_event, track=other_track)

        response = panel_client.post(
            self.get_url(event), data={"track_pk": other_track.pk}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_item.refresh_from_db()
        assert other_item.session_confirmed is False

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:timetable-confirm-block", kwargs={"slug": "nonexistent"})

        response = panel_client.post(url, data={"track_pk": 1})

        assert_event_not_found(response)
