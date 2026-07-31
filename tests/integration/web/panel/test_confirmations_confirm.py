from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import AgendaItem, Event, Facilitator, Track
from tests.integration.conftest import (
    AgendaItemFactory,
    ProposalCategoryFactory,
    SessionFactory,
)


def _confirm_url(event):
    return reverse("panel:timetable-confirmations-confirm", kwargs={"slug": event.slug})


def _schedule(
    *, category, facilitator, track, email="ada@example.com", confirmed=False
):
    session = SessionFactory(category=category, status="accepted", contact_email=email)
    session.facilitators.add(facilitator)
    session.tracks.add(track)
    return AgendaItemFactory(session=session, session_confirmed=confirmed)


class TestConfirmationsConfirmActionView:
    """Tests for /panel/event/<slug>/timetable/confirmations/do/confirm."""

    def test_rejects_get(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)

        response = authenticated_client.get(_confirm_url(event))

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_confirms_one_program_item(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        item = _schedule(
            category=proposal_category, facilitator=facilitator, track=track
        )
        other = _schedule(
            category=proposal_category, facilitator=facilitator, track=track
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "session",
                "facilitator_pk": facilitator.pk,
                "track_pk": track.pk,
                "agenda_item_pk": item.pk,
                "confirmed": "true",
            },
        )

        assert response.status_code == HTTPStatus.OK
        item.refresh_from_db()
        other.refresh_from_db()
        assert item.session_confirmed
        assert not other.session_confirmed

    def test_missing_confirmed_flag_undoes_the_confirmation(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        item = _schedule(
            category=proposal_category,
            facilitator=facilitator,
            track=track,
            confirmed=True,
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "session",
                "facilitator_pk": facilitator.pk,
                "track_pk": track.pk,
                "agenda_item_pk": item.pk,
            },
        )

        assert response.status_code == HTTPStatus.OK
        item.refresh_from_db()
        assert not item.session_confirmed

    def test_confirms_one_contact_address_only(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        mine = _schedule(
            category=proposal_category, facilitator=facilitator, track=track
        )
        elsewhere = _schedule(
            category=proposal_category,
            facilitator=facilitator,
            track=track,
            email="club@example.org",
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "email",
                "facilitator_pk": facilitator.pk,
                "track_pk": track.pk,
                "contact_email": "ada@example.com",
                "confirmed": "true",
            },
        )

        assert response.status_code == HTTPStatus.OK
        mine.refresh_from_db()
        elsewhere.refresh_from_db()
        assert mine.session_confirmed
        assert not elsewhere.session_confirmed

    def test_confirms_the_facilitators_whole_event(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        other_track = Track.objects.create(event=event, name="Talks", slug="talks")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        here = _schedule(
            category=proposal_category, facilitator=facilitator, track=track
        )
        elsewhere = _schedule(
            category=proposal_category,
            facilitator=facilitator,
            track=other_track,
            email="club@example.org",
        )
        somebody_else = Facilitator.objects.create(
            event=event, display_name="Ben", slug="ben"
        )
        untouched = _schedule(
            category=proposal_category, facilitator=somebody_else, track=track
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "facilitator",
                "facilitator_pk": facilitator.pk,
                "track_pk": track.pk,
                "confirmed": "true",
            },
        )

        assert response.status_code == HTTPStatus.OK
        for item in (here, elsewhere, untouched):
            item.refresh_from_db()
        assert here.session_confirmed
        assert elsewhere.session_confirmed
        assert not untouched.session_confirmed

    def test_returns_the_re_rendered_card(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        item = _schedule(
            category=proposal_category, facilitator=facilitator, track=track
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "session",
                "facilitator_pk": facilitator.pk,
                "track_pk": track.pk,
                "agenda_item_pk": item.pk,
                "confirmed": "true",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert (
            response.templates[0].name
            == "panel/parts/confirmation-facilitator-card.html"
        )
        card = response.context["facilitator"]
        assert card.confirmed_count == 1
        assert card.is_fully_confirmed

    def test_rejects_a_facilitator_from_another_event(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        foreign_event = Event.objects.create(
            sphere=sphere,
            name="Other",
            slug="other",
            start_time=event.start_time,
            end_time=event.end_time,
        )
        foreign_facilitator = Facilitator.objects.create(
            event=foreign_event, display_name="Ada", slug="ada"
        )
        foreign_item = _schedule(
            category=ProposalCategoryFactory(event=foreign_event),
            facilitator=foreign_facilitator,
            track=Track.objects.create(
                event=foreign_event, name="RPG", slug="rpg-other"
            ),
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "facilitator",
                "facilitator_pk": foreign_facilitator.pk,
                "track_pk": track.pk,
                "confirmed": "true",
            },
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        foreign_item.refresh_from_db()
        assert not foreign_item.session_confirmed

    def test_rejects_an_agenda_item_of_another_facilitator(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        somebody_else = Facilitator.objects.create(
            event=event, display_name="Ben", slug="ben"
        )
        theirs = _schedule(
            category=proposal_category, facilitator=somebody_else, track=track
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "session",
                "facilitator_pk": facilitator.pk,
                "track_pk": track.pk,
                "agenda_item_pk": theirs.pk,
                "confirmed": "true",
            },
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        theirs.refresh_from_db()
        assert not theirs.session_confirmed

    def test_rejects_a_malformed_request(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _confirm_url(event),
            {"scope": "session", "facilitator_pk": "abc", "track_pk": "1"},
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_unscheduled_session_cannot_be_confirmed(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        unplaced = SessionFactory(category=proposal_category, status="accepted")
        unplaced.facilitators.add(facilitator)
        unplaced.tracks.add(track)

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "facilitator",
                "facilitator_pk": facilitator.pk,
                "track_pk": track.pk,
                "confirmed": "true",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert not AgendaItem.objects.filter(session=unplaced).exists()
