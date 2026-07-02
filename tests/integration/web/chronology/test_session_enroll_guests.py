from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Party,
    SessionParticipation,
    SessionParticipationStatus,
    User,
)
from ludamus.pacts.crowd import UserType
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response


def _url(agenda_item):
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={
            "event_slug": agenda_item.session.event.slug,
            "session_id": agenda_item.session.pk,
        },
    )


def _allow_guests(enrollment_config):
    enrollment_config.allow_anonymous_enrollment = True
    enrollment_config.save()


def _reassign_presenter(agenda_item):
    agenda_item.session.presenter = UserFactory(username="host", name="Host")
    agenda_item.session.save()


def _guests(agenda_item, viewer):
    return SessionParticipation.objects.filter(
        session=agenda_item.session,
        enrolled_by=viewer,
        user__user_type=UserType.ANONYMOUS,
    )


class TestGuestStepperVisibility:
    @pytest.mark.usefixtures("enrollment_config")
    def test_hidden_when_anonymous_enrollment_disabled(
        self, authenticated_client, agenda_item
    ):
        response = authenticated_client.get(_url(agenda_item))

        assert response.status_code == HTTPStatus.OK
        assert "Bringing guests" not in response.content.decode()

    def test_shown_when_anonymous_enrollment_enabled(
        self, authenticated_client, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)

        response = authenticated_client.get(_url(agenda_item))

        assert response.status_code == HTTPStatus.OK
        assert "Bringing guests" in response.content.decode()


class TestGuestEnrollment:
    def test_post_brings_two_guests(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(_url(agenda_item), data={"guests": "2"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/chronology/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, "Guests you bring: 2")],
        )
        guests = _guests(agenda_item, active_user)
        assert [g.status for g in guests] == [
            SessionParticipationStatus.CONFIRMED,
            SessionParticipationStatus.CONFIRMED,
        ]
        for participation in guests:
            assert participation.user.name == f"{active_user.name} +1"
            assert not participation.user.is_active

    def test_post_lowering_count_removes_guests_and_their_rows(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        authenticated_client.post(_url(agenda_item), data={"guests": "3"})

        response = authenticated_client.post(_url(agenda_item), data={"guests": "1"})

        assert response.status_code == HTTPStatus.FOUND
        assert _guests(agenda_item, active_user).count() == 1
        assert (
            User.objects.filter(
                user_type=UserType.ANONYMOUS, username__startswith="anon_"
            ).count()
            == 1
        )

    @pytest.mark.usefixtures("active_user")
    def test_freed_guest_seat_promotes_the_waitlist(
        self, authenticated_client, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        agenda_item.session.participants_limit = 2
        agenda_item.session.save()
        authenticated_client.post(_url(agenda_item), data={"guests": "2"})
        waiter = UserFactory(username="waiting", name="Wanda Waiting")
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=waiter,
            status=SessionParticipationStatus.WAITING,
        )

        authenticated_client.post(_url(agenda_item), data={"guests": "1"})

        waiting = SessionParticipation.objects.get(user=waiter)
        assert waiting.status == SessionParticipationStatus.CONFIRMED

    def test_post_rejects_more_guests_than_seats(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        agenda_item.session.participants_limit = 2
        agenda_item.session.save()

        response = authenticated_client.post(_url(agenda_item), data={"guests": "3"})

        assert _guests(agenda_item, active_user).count() == 0
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[
                (
                    messages.ERROR,
                    (
                        "Not enough spots available. 3 spots requested, 2 available. "
                        "Please use waiting list for some users."
                    ),
                )
            ],
        )

    @pytest.mark.usefixtures("connected_user")
    def test_guests_join_the_selected_party_group(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        party = Party.objects.get(leader=active_user)

        authenticated_client.post(
            _url(agenda_item), data={"party": str(party.pk), "guests": "1"}
        )

        guest = _guests(agenda_item, active_user).get()
        assert guest.party_id == party.pk
