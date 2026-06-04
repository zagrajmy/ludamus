from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse
from django.utils import timezone

from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_response, assert_response_404


def _confirmed_item(event, session, space):
    return AgendaItemFactory(
        session=session,
        space=space,
        session_confirmed=True,
        start_time=event.start_time,
        end_time=event.start_time + timedelta(hours=1),
    )


class TestPublicEventPrintView:
    URL_NAME = "web:chronology:event-print"

    def _url(self, slug):
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_ok_renders_confirmed_session(self, client, event, session, space):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/print.html",
            context_data={
                "event": ANY,
                "timetable": ANY,
                "area_schedule": ANY,
                "qr_svg": ANY,
                "venues": ANY,
                "selected_venue": "",
                "selected_area": "",
                "range_start_value": ANY,
                "range_hours": 6,
            },
        )
        content = response.content.decode()
        assert session.title in content
        # The per-area pages carry the full description; the grid does not.
        assert session.description in content

    def test_unconfirmed_session_is_hidden(self, client, event, session, space):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=False,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/print.html",
            context_data={
                "event": ANY,
                "timetable": ANY,
                "area_schedule": ANY,
                "qr_svg": ANY,
                "venues": ANY,
                "selected_venue": "",
                "selected_area": "",
                "range_start_value": ANY,
                "range_hours": 6,
            },
        )
        assert session.title not in response.content.decode()

    def test_full_schedule_label_shown_when_a_session_is_pending(
        self, client, event, session, space, sphere, active_user
    ):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )
        pending = SessionFactory(
            presenter=active_user, sphere=sphere, participants_limit=10
        )
        AgendaItemFactory(
            session=pending,
            space=SpaceFactory(area=space.area, name="Side Room"),
            session_confirmed=False,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        assert "Full schedule" in response.content.decode()

    def test_full_schedule_label_hidden_when_complete(
        self, client, event, session, space
    ):
        AgendaItemFactory(
            session=session,
            space=space,
            session_confirmed=True,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=1),
        )

        response = client.get(self._url(event.slug))

        assert "Full schedule" not in response.content.decode()

    def test_unpublished_event_is_not_found_for_anonymous(self, client, event):
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()

        response = client.get(self._url(event.slug))

        assert_response_404(response)

    def test_missing_event_is_not_found(self, client):
        response = client.get(self._url("does-not-exist"))

        assert_response_404(response)

    def test_manager_previews_unpublished_event(
        self, authenticated_client, active_user, sphere, event, session, space
    ):
        sphere.managers.add(active_user)
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()
        _confirmed_item(event, session, space)

        response = authenticated_client.get(self._url(event.slug))

        assert response.status_code == HTTPStatus.OK
        assert session.title in response.content.decode()

    def test_scoped_to_venue_shows_logo_capacity_and_scope_name(
        self, client, event, session, venue, space
    ):
        event.logo = "events/logo.png"
        event.save()
        space.capacity = 30
        space.save()
        _confirmed_item(event, session, space)

        response = client.get(f"{self._url(event.slug)}?venue={venue.slug}")

        content = response.content.decode()
        assert response.status_code == HTTPStatus.OK
        assert "events/logo.png" in content  # logo header
        assert venue.name in content  # scope name
        assert "Full schedule" in content  # a scoped print is never the whole thing
        assert "30" in content  # space capacity

    def test_scoped_to_area_resolves_area_scope(
        self, client, event, session, venue, area, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(
            f"{self._url(event.slug)}?venue={venue.slug}&area={area.slug}"
        )

        assert response.status_code == HTTPStatus.OK
        assert area.name in response.content.decode()
        assert response.context_data["selected_area"] == area.slug

    def test_invalid_range_params_fall_back_to_defaults(
        self, client, event, session, space
    ):
        _confirmed_item(event, session, space)

        response = client.get(
            f"{self._url(event.slug)}?hours=nope&start=2026-13-40T99:99"
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/print.html",
            context_data=ANY,
        )

    def test_explicit_start_and_hours_are_applied(self, client, event, session, space):
        _confirmed_item(event, session, space)
        start = event.start_time.strftime("%Y-%m-%dT%H:%M")
        hours = 3

        response = client.get(f"{self._url(event.slug)}?start={start}&hours={hours}")

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["range_hours"] == hours

    def test_unknown_venue_is_not_found(self, client, event):
        response = client.get(f"{self._url(event.slug)}?venue=does-not-exist")

        assert_response_404(response)

    def test_event_without_venues_renders_empty_states(self, client, sphere):
        bare = EventFactory(sphere=sphere, slug="bare-event")

        response = client.get(self._url(bare.slug))

        assert response.status_code == HTTPStatus.OK


class TestEventPagePrintHijack:
    def test_event_page_points_to_print_page(self, client, event):
        url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        print_url = reverse("web:chronology:event-print", kwargs={"slug": event.slug})

        content = client.get(url).content.decode()

        # The hijack anchor (read by event-print.ts) and the @media print
        # fallback both reference the public print page.
        assert "data-event-print" in content
        assert print_url in content
