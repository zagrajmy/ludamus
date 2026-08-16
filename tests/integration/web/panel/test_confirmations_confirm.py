from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import AgendaItem, Event, Facilitator, Track
from ludamus.pacts import EventDTO
from ludamus.pacts.event import (
    ConfirmationEmailGroupDTO,
    ConfirmationFacilitatorDTO,
    ConfirmationSessionDTO,
    ConfirmationStatusGroupDTO,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    ProposalCategoryFactory,
    SessionFactory,
)
from tests.integration.utils import assert_response


def _confirm_url(event):
    return reverse("panel:timetable-confirmations-confirm", kwargs={"slug": event.slug})


def _schedule(
    *, category, facilitator, track, email="ada@example.com", confirmed=False
):
    session = SessionFactory(category=category, status="accepted", contact_email=email)
    session.facilitators.add(facilitator)
    session.tracks.add(track)
    return AgendaItemFactory(session=session, session_confirmed=confirmed)


def _scheduled_group(*items, other_track_names=()):
    # One contact address, its placed program in the order the card renders it:
    # by start time, and every item of these fixtures is placed.
    return ConfirmationEmailGroupDTO(
        contact_email=items[0].session.contact_email,
        status_groups=[
            ConfirmationStatusGroupDTO(
                status="scheduled",
                sessions=[
                    ConfirmationSessionDTO(
                        session_pk=item.session.pk,
                        title=item.session.title,
                        category_name=item.session.category.name,
                        room_name=item.space.name,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        agenda_item_pk=item.pk,
                        is_confirmed=item.session_confirmed,
                        co_facilitator_names=[],
                        other_track_names=list(other_track_names),
                    )
                    for item in items
                ],
            )
        ],
        confirmable_count=len(items),
    )


def _card(facilitator, *groups, confirmed_count, scheduled_count):
    return ConfirmationFacilitatorDTO(
        display_name=facilitator.display_name,
        organizer_name="",
        organizer_id=None,
        pk=facilitator.pk,
        slug=facilitator.slug,
        email_groups=list(groups),
        scheduled_count=scheduled_count,
        confirmed_count=confirmed_count,
        unplaced_count=0,
        pending_count=0,
        is_fully_confirmed=bool(scheduled_count) and confirmed_count == scheduled_count,
    )


def _card_context(event, track, facilitator, *groups, confirmed_count, scheduled_count):
    return {
        "facilitator": _card(
            facilitator,
            *groups,
            confirmed_count=confirmed_count,
            scheduled_count=scheduled_count,
        ),
        "slug": event.slug,
        "current_event": EventDTO.model_validate(event),
        "filter_track_pk": track.pk,
        "next_url": "",
    }


_CARD_TEMPLATE = "panel/parts/confirmation-facilitator-card.html"


class TestConfirmationsConfirmActionView:
    """Tests for /panel/event/<slug>/timetable/confirmations/do/confirm."""

    def test_rejects_get(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)

        response = authenticated_client.get(_confirm_url(event))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

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

        item.refresh_from_db()
        other.refresh_from_db()
        assert item.session_confirmed
        assert not other.session_confirmed
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_CARD_TEMPLATE,
            context_data=_card_context(
                event,
                track,
                facilitator,
                _scheduled_group(item, other),
                confirmed_count=1,
                scheduled_count=2,
            ),
        )

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

        item.refresh_from_db()
        assert not item.session_confirmed
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_CARD_TEMPLATE,
            context_data=_card_context(
                event,
                track,
                facilitator,
                _scheduled_group(item),
                confirmed_count=0,
                scheduled_count=1,
            ),
        )

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

        mine.refresh_from_db()
        elsewhere.refresh_from_db()
        assert mine.session_confirmed
        assert not elsewhere.session_confirmed
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_CARD_TEMPLATE,
            context_data=_card_context(
                event,
                track,
                facilitator,
                _scheduled_group(mine),
                _scheduled_group(elsewhere),
                confirmed_count=1,
                scheduled_count=2,
            ),
        )

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

        for item in (here, elsewhere, untouched):
            item.refresh_from_db()
        assert here.session_confirmed
        assert elsewhere.session_confirmed
        assert not untouched.session_confirmed
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_CARD_TEMPLATE,
            context_data=_card_context(
                event,
                track,
                facilitator,
                _scheduled_group(here),
                _scheduled_group(elsewhere, other_track_names=["Talks"]),
                confirmed_count=2,
                scheduled_count=2,
            ),
        )

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

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        foreign_item.refresh_from_db()
        assert not foreign_item.session_confirmed

    def test_rejects_a_track_from_another_event(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada"
        )
        item = _schedule(
            category=proposal_category,
            facilitator=facilitator,
            track=Track.objects.create(event=event, name="RPG", slug="rpg"),
        )
        foreign_event = Event.objects.create(
            sphere=sphere,
            name="Other",
            slug="other",
            start_time=event.start_time,
            end_time=event.end_time,
        )
        foreign_track = Track.objects.create(
            event=foreign_event, name="RPG", slug="rpg-other"
        )

        response = authenticated_client.post(
            _confirm_url(event),
            {
                "scope": "session",
                "facilitator_pk": facilitator.pk,
                "track_pk": foreign_track.pk,
                "agenda_item_pk": item.pk,
                "confirmed": "true",
            },
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

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

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
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

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)

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

        assert not AgendaItem.objects.filter(session=unplaced).exists()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_CARD_TEMPLATE,
            context_data=_card_context(
                event, track, facilitator, confirmed_count=0, scheduled_count=0
            )
            | {
                "facilitator": (
                    _card(facilitator, confirmed_count=0, scheduled_count=0).model_copy(
                        update={"unplaced_count": 1}
                    )
                )
            },
        )
