from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Party,
    SessionParticipation,
    SessionParticipationStatus,
    User,
    UserEnrollmentConfig,
)
from ludamus.adapters.web.django.entities import SessionUserParticipationData
from ludamus.inits.services import Services
from ludamus.pacts.crowd import UserDTO, UserType
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


def _page_context(viewer, agenda_item):
    selection = Services().parties.enrollment_selection(
        viewer_pk=viewer.pk, requested_party=None
    )
    return {
        "party_choices": selection.choices,
        "selected_party": selection.selected,
        "connected_users": [],
        "event": agenda_item.session.event,
        "form": ANY,
        "session": agenda_item.session,
        "shadowban_warnings": [],
        "user_data": [
            SessionUserParticipationData(
                user=UserDTO.model_validate(viewer),
                user_enrolled=False,
                user_waiting=False,
                has_time_conflict=False,
            )
        ],
    }


class TestGuestStepperVisibility:
    @pytest.mark.usefixtures("enrollment_config")
    def test_hidden_when_anonymous_enrollment_disabled(
        self, authenticated_client, active_user, agenda_item
    ):
        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_page_context(active_user, agenda_item),
            template_name="chronology/enroll_select.html",
            not_contains="Guests without an account",
        )

    def test_shown_with_bounds_and_zero_prefill(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)

        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_page_context(active_user, agenda_item),
            template_name="chronology/enroll_select.html",
            contains=[
                "Guests without an account",
                'name="guests"',
                'min="0"',
                'max="10"',
                'value="0"',
            ],
        )

    def test_prefilled_with_the_current_guest_count(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        authenticated_client.post(_url(agenda_item), data={"guests": "3"}, follow=True)

        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_page_context(active_user, agenda_item),
            template_name="chronology/enroll_select.html",
            contains='value="3"',
            not_contains='value="0"',
        )


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
            url=f"/event/{agenda_item.session.event.slug}/",
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

    def test_repeating_the_same_target_is_a_noop(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        authenticated_client.post(_url(agenda_item), data={"guests": "2"}, follow=True)

        response = authenticated_client.post(_url(agenda_item), data={"guests": "2"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[(messages.WARNING, "No changes.")],
        )
        assert _guests(agenda_item, active_user).count() == 1 + 1  # still two guests

    def test_post_lowering_count_removes_guests_and_their_rows(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        authenticated_client.post(_url(agenda_item), data={"guests": "3"}, follow=True)

        response = authenticated_client.post(_url(agenda_item), data={"guests": "1"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, "Guests you bring: 1")],
        )
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
        authenticated_client.post(_url(agenda_item), data={"guests": "2"}, follow=True)
        waiter = UserFactory(username="waiting", name="Wanda Waiting")
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=waiter,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.post(_url(agenda_item), data={"guests": "1"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, "Guests you bring: 1")],
        )
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
                        "Bring fewer guests or use the waiting list for account "
                        "holders."
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

        response = authenticated_client.post(
            _url(agenda_item), data={"party": str(party.pk), "guests": "1"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, "Guests you bring: 1")],
        )
        guest = _guests(agenda_item, active_user).get()
        assert guest.party_id == party.pk

    def test_restricted_viewer_without_slots_can_still_bring_guests(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        # Guests intentionally bypass the membership slot cap: walk-ins have no
        # membership, and their seats come from the session's capacity pool.
        _allow_guests(enrollment_config)
        _reassign_presenter(agenda_item)
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=datetime.now(UTC),
        )

        response = authenticated_client.post(_url(agenda_item), data={"guests": "1"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, "Guests you bring: 1")],
        )
        assert _guests(agenda_item, active_user).count() == 1
