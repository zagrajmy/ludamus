import threading
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from unittest.mock import ANY, Mock, patch

import pytest
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import Client
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    AgendaItem,
    EnrollmentConfig,
    Notification,
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
    UserEnrollmentConfig,
)
from ludamus.adapters.web.django.entities import SessionUserParticipationData
from ludamus.inits.services import Services
from ludamus.pacts.crowd import ConnectedUserDTO, UserDTO
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
    UserFactory,
    sponsor_user,
)
from tests.integration.utils import assert_response, input_tag


def _party_context(viewer):
    # The enroll page's party plumbing, derived from the same service call the
    # view makes (default selection: no explicit party requested).
    selection = Services().parties.enrollment_selection(
        viewer_pk=viewer.pk, requested_party=None
    )
    return {"party_choices": selection.choices, "selected_party": selection.selected}


class TestSessionEnrollPageView:
    URL_NAME = "web:chronology:session-enrollment"

    def _get_url(self, session_id: int, event_slug: str) -> str:
        return reverse(
            self.URL_NAME, kwargs={"event_slug": event_slug, "session_id": session_id}
        )

    def test_get_get_ok(self, active_user, authenticated_client, agenda_item):
        response = authenticated_client.get(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    def test_get_renders_one_include_checkbox_per_row(
        self, active_user, connected_user, authenticated_client, agenda_item
    ):
        # The desired-state redesign: one "Include" checkbox per person, checked
        # when they are already in, unchecked otherwise. No enroll/waitlist split.
        connected_user.name = "Connected Person"
        connected_user.save()
        SessionParticipation.objects.create(
            user=connected_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.get(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                **_party_context(active_user),
                "connected_users": [ConnectedUserDTO.model_validate(connected_user)],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=ConnectedUserDTO.model_validate(connected_user),
                        user_enrolled=True,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
            },
            template_name="chronology/enroll_select.html",
        )
        content = " ".join(response.content.decode().split())
        assert 'name="enroll_mode" value="desired"' in content
        for user in (active_user, connected_user):
            assert f'name="user_{user.pk}" value="include"' in content
        # The already-enrolled companion starts checked.
        assert input_tag(content, connected_user.pk).count("checked") == 1

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_no_change_value_leaves_user_unenrolled(
        self, connected_user, agenda_item, authenticated_client
    ):
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{connected_user.id}": ""},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "Please select at least one user to enroll.")],
            url=self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
        )
        assert not SessionParticipation.objects.filter(
            user=connected_user, session=agenda_item.session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_get_offered_participation_only_offers_decline(
        self, active_user, authenticated_client, agenda_item
    ):
        # A held offer lets the user only decline it; the page surfaces the
        # "Decline offer" choice instead of enroll/waitlist actions.
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.OFFERED,
        )

        response = authenticated_client.get(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        offer_pending=True,
                        has_time_conflict=False,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
            contains=["Spot offered"],
        )
        field = response.context_data["form"].fields[f"user_{active_user.pk}"]
        assert ("cancel", "Decline offer") in list(field.choices)
        content = " ".join(response.content.decode().split())
        # The generic pending-offer chip (not the leader-held-seat one). The
        # Include box starts checked (they hold a spot) and stays toggleable, so
        # unchecking it declines the offer.
        assert "Spot offered" in content
        assert "Seat held" not in content
        tag = input_tag(content, active_user.pk)
        assert "checked" in tag
        assert "disabled" not in tag

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_decline_offered(
        self, active_user, agenda_item, authenticated_client, event
    ):
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.OFFERED,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    def test_get_error_404(self, authenticated_client, event):
        response = authenticated_client.get(self._get_url(17, event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url="/",
        )

    def test_get_unscheduled_session_rejected(
        self, authenticated_client, pending_session
    ):
        response = authenticated_client.get(
            self._get_url(pending_session.pk, pending_session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "No enrollment configuration is available for this session.",
                )
            ],
            url="/",
        )

    def test_post_error_enrollment_inactive(
        self, agenda_item, authenticated_client, event, faker, time_zone
    ):
        EnrollmentConfig.objects.create(
            event=event,
            start_time=faker.date_time_between("-10d", "-5d", tzinfo=time_zone),
            end_time=faker.date_time_between("-4d", "-1d", tzinfo=time_zone),
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "No enrollment configuration is available for this session.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_post_cancel_when_enrollment_inactive(
        self, agenda_item, authenticated_client, event, faker, time_zone, active_user
    ):
        EnrollmentConfig.objects.create(
            event=event,
            start_time=faker.date_time_between("-10d", "-5d", tzinfo=time_zone),
            end_time=faker.date_time_between("-4d", "-1d", tzinfo=time_zone),
        )
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    def test_post_cancel_when_no_enrollment_config(
        self, agenda_item, authenticated_client, event, active_user
    ):
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "No enrollment configuration is available for this session.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_post_invalid_form(self, active_user, agenda_item, authenticated_client):
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "wrong data"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (messages.ERROR, "Invalid choice for Test User: wrong data"),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_error_please_select_at_least_one(
        self, agenda_item, authenticated_client
    ):
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "Please select at least one user to enroll.")],
            url=self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_ok(self, staff_user, agenda_item, staff_client, event):
        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {staff_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        SessionParticipation.objects.get(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_ok_unlimited_session(
        self, staff_user, agenda_item, staff_client, session, event
    ):
        session.participants_limit = 0
        session.save()

        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {staff_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        SessionParticipation.objects.get(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel(self, active_user, agenda_item, authenticated_client, event):
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel_waiting(
        self, active_user, agenda_item, authenticated_client, event
    ):
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel_without_enrollment_skips(
        self, active_user, agenda_item, authenticated_client, event
    ):
        # A cancel choice for a user with no participation is only reachable
        # when a concurrent request deleted the row first; the form would
        # otherwise reject "cancel". Mock the form to simulate that race and
        # assert we skip gracefully instead of raising StopIteration.
        with patch(
            "ludamus.adapters.web.django.views.create_enrollment_form"
        ) as mock_form_factory:
            mock_form_class = Mock()
            mock_form_instance = Mock()
            mock_form_instance.is_valid.return_value = True
            mock_form_instance.cleaned_data = {f"user_{active_user.id}": "cancel"}
            mock_form_class.return_value = mock_form_instance
            mock_form_factory.return_value = mock_form_class

            response = authenticated_client.post(
                self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
                data={f"user_{active_user.id}": "cancel"},
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Skipped (already enrolled or conflicts): "
                        f"{active_user.name} (no enrollment to cancel)"
                    ),
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    @pytest.mark.postgres
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.usefixtures("enrollment_config")
    def test_concurrent_cancel_does_not_500(self, active_user, agenda_item):
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        url = self._get_url(agenda_item.session.pk, agenda_item.session.event.slug)
        post_data = {f"user_{active_user.id}": "cancel"}

        clients = []
        for _ in range(2):
            client = Client()
            client.force_login(active_user)
            clients.append(client)

        barrier = threading.Barrier(len(clients))

        def cancel(client):
            barrier.wait()
            try:
                return client.post(url, data=post_data)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(clients)) as pool:
            responses = [
                future.result()
                for future in [pool.submit(cancel, client) for client in clients]
            ]

        assert all(response.status_code == HTTPStatus.FOUND for response in responses)
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel_promote(
        self, active_user, agenda_item, authenticated_client, event, connected_user
    ):
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        SessionParticipation.objects.create(
            user=connected_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        # The promotee is notified directly now; the canceller only sees their
        # own cancellation (no "stolen" promotion message).
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()
        assert SessionParticipation.objects.filter(
            user=connected_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        ).exists()
        # The manager of the promoted minor is notified directly.
        assert Notification.objects.filter(
            recipient=active_user, kind=NotificationKind.WAITLIST_PROMOTED.value
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post__error_conflict(self, active_user, agenda_item, authenticated_client):
        other_session = SessionFactory(
            display_name=active_user.name,
            event=agenda_item.session.event,
            participants_limit=10,
        )
        AgendaItem.objects.create(
            session=other_session,
            space=agenda_item.space,
            start_time=agenda_item.start_time,
            end_time=agenda_item.end_time,
        )
        SessionParticipation.objects.create(
            user=active_user,
            session=other_session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. enroll is not one of the available "
                        "choices."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,  # User is not enrolled in THIS session
                        user_waiting=False,
                        has_time_conflict=True,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_invalid_capacity(
        self, active_user, agenda_item, authenticated_client, session, connected_user
    ):
        session.participants_limit = 1
        session.save()
        SessionParticipation.objects.create(
            user=connected_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Not enough spots available. 1 spots requested, 0 available. "
                        "Please use waiting list for some users."
                    ),
                )
            ],
            url=reverse(
                "web:chronology:session-enrollment",
                kwargs={"event_slug": session.event.slug, "session_id": session.id},
            ),
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel_and_enroll_on_full_session(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        session,
        connected_user,
        event,
    ):
        session.participants_limit = 1
        session.save()
        SessionParticipation.objects.create(
            user=active_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={
                f"user_{active_user.id}": "cancel",
                f"user_{connected_user.id}": "enroll",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, f"Enrolled: {connected_user.name}"),
                (messages.SUCCESS, f"Cancelled: {active_user.name}"),
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=session
        ).exists()
        SessionParticipation.objects.get(
            user=connected_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_connected_user_inactive(
        self, agenda_item, authenticated_client, session, connected_user
    ):
        connected_user.is_active = False
        connected_user.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "Please select at least one user to enroll.")],
            url=reverse(
                "web:chronology:session-enrollment",
                kwargs={"event_slug": session.event.slug, "session_id": session.id},
            ),
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_session_host_skipped(
        self, authenticated_client, agenda_item, proposal_category, active_user
    ):

        session = agenda_item.session
        session.presenter = active_user
        session.save()

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "Skipped (already enrolled or conflicts): Test User (session host)",
                )
            ],
            url=f"/event/{proposal_category.event.slug}/",
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    @staticmethod
    def test_post_time_conflict_skipped(authenticated_client, active_user, event):
        space1 = SpaceFactory(event=event)
        space2 = SpaceFactory(event=event)
        time_slot = TimeSlotFactory(event=event)

        session1 = SessionFactory(event=event)
        AgendaItemFactory(
            session=session1,
            space=space1,
            start_time=time_slot.start_time,
            end_time=time_slot.end_time,
        )
        SessionParticipation.objects.create(
            user=active_user,
            session=session1,
            status=SessionParticipationStatus.CONFIRMED,
        )

        session2 = SessionFactory(event=event)
        AgendaItemFactory(
            session=session2,
            space=space2,
            start_time=time_slot.start_time,
            end_time=time_slot.end_time,
        )

        with patch(
            "ludamus.adapters.web.django.views.create_enrollment_form"
        ) as mock_form_factory:
            mock_form_class = Mock()
            mock_form_instance = Mock()
            mock_form_instance.is_valid.return_value = True
            mock_form_instance.cleaned_data = {f"user_{active_user.id}": "enroll"}
            mock_form_class.return_value = mock_form_instance
            mock_form_factory.return_value = mock_form_class

            response = authenticated_client.post(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={
                        "event_slug": session2.event.slug,
                        "session_id": session2.id,
                    },
                ),
                data={f"user_{active_user.id}": "enroll"},
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Skipped (already enrolled or conflicts): Test User "
                        "(time conflict)"
                    ),
                )
            ],
            url=f"/event/{event.slug}/",
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=session2
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_no_user_selected(self, authenticated_client, agenda_item):
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={},  # No user selections
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "Please select at least one user to enroll.")],
            url=reverse(
                "web:chronology:session-enrollment",
                kwargs={
                    "event_slug": agenda_item.session.event.slug,
                    "session_id": agenda_item.session.id,
                },
            ),
        )

    def test_post_restrict_to_configured_users(
        self, staff_user, agenda_item, staff_client, event, enrollment_config
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        f"{staff_user.name} cannot enroll: enrollment access "
                        "permission required"
                    ),
                ),
                (
                    messages.ERROR,
                    (
                        "Enrollment access permission is required for this session. "
                        "Please contact the organizers to obtain access."
                    ),
                ),
            ],
            context_data={
                **_party_context(staff_user),
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(staff_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_restrict_to_configured_users_without_email(
        self, staff_user, agenda_item, staff_client, event, enrollment_config
    ):
        staff_user.email = ""
        staff_user.save()
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    f"{staff_user.name} cannot enroll: email address required",
                ),
                (
                    messages.ERROR,
                    "Email address is required for enrollment in this session.",
                ),
            ],
            context_data={
                **_party_context(staff_user),
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(staff_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_restrict_to_configured_users_config_exists(
        self, staff_user, agenda_item, staff_client, event, enrollment_config
    ):
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=staff_user.email,
            allowed_slots=1,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "wrong"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (messages.ERROR, f"Invalid choice for {staff_user.name}: wrong"),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(staff_user),
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(staff_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_restrict_to_configured_users_config_exists_too_many_enrollment(
        self,
        staff_user,
        agenda_item,
        staff_client,
        event,
        enrollment_config,
        connected_user,
    ):
        PartyMembership.objects.filter(member=connected_user).delete()
        sponsor_user(leader=staff_user, member=connected_user)
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=staff_user.email,
            allowed_slots=1,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={
                f"user_{staff_user.id}": "enroll",
                f"user_{connected_user.id}": "enroll",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        f"{staff_user.name}: Cannot enroll more users. You have "
                        "already enrolled 0 out of 1 unique people (each person can "
                        "enroll in multiple sessions). Only 1 slots remaining for "
                        "new people."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(staff_user),
                "connected_users": [ConnectedUserDTO.model_validate(connected_user)],
                "session": agenda_item.session,
                "event": event,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(staff_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=ConnectedUserDTO.model_validate(connected_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_restrict_to_configured_users_config_exists_success(
        self, staff_user, agenda_item, staff_client, event, enrollment_config
    ):
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=staff_user.email,
            allowed_slots=1,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {staff_user.name}")],
            url=f"/event/{event.slug}/",
        )

    def test_post_restrict_to_configured_users_config_exists_too_many_enrollment2(
        self,
        staff_user,
        agenda_item,
        staff_client,
        event,
        enrollment_config,
        connected_user,
    ):
        PartyMembership.objects.filter(member=connected_user).delete()
        sponsor_user(leader=staff_user, member=connected_user)
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=staff_user.email,
            allowed_slots=1,
        )
        SessionParticipation.objects.create(
            user=connected_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        f"{staff_user.name}: Cannot enroll more users. You have "
                        "already enrolled 1 out of 1 unique people (each person can "
                        "enroll in multiple sessions). Only 0 slots remaining for "
                        "new people."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(staff_user),
                "connected_users": [ConnectedUserDTO.model_validate(connected_user)],
                "session": agenda_item.session,
                "event": event,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(staff_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=ConnectedUserDTO.model_validate(connected_user),
                        user_enrolled=True,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel_promote_no_email(
        self, active_user, agenda_item, authenticated_client, event, connected_user
    ):
        connected_user.email = ""
        connected_user.save()
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        SessionParticipation.objects.create(
            user=connected_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()
        assert SessionParticipation.objects.filter(
            user=connected_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel_promote_staff_user(
        self, active_user, agenda_item, authenticated_client, event, staff_user
    ):
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        SessionParticipation.objects.create(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()
        assert SessionParticipation.objects.filter(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        ).exists()

    def test_post_cancel_promote_cant_be_promoted(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        event,
        staff_user,
        enrollment_config,
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=1,
        )
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=staff_user.email,
            allowed_slots=0,
        )
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        SessionParticipation.objects.create(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    def test_post_restrict_to_configured_users_connected_user(
        self,
        active_user,
        connected_user,
        agenda_item,
        authenticated_client,
        event,
        enrollment_config,
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=1,
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {connected_user.name}")],
            url=f"/event/{event.slug}/",
        )

    def test_post_cant_join_waitlist(
        self, active_user, agenda_item, enrollment_config, authenticated_client
    ):
        enrollment_config.max_waitlist_sessions = 0
        enrollment_config.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "waitlist"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. waitlist is not one of the available "
                        "choices."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_connected_user_cant_join_waitlist_no_manager_user_config(
        self,
        active_user,
        connected_user,
        agenda_item,
        enrollment_config,
        authenticated_client,
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{connected_user.id}": "waitlist"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. waitlist is not one of the available "
                        "choices."
                    ),
                ),
                (
                    messages.ERROR,
                    (
                        "Enrollment access permission is required for this session. "
                        "Please contact the organizers to obtain access."
                    ),
                ),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [ConnectedUserDTO.model_validate(connected_user)],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=ConnectedUserDTO.model_validate(connected_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_connected_user_cant_enroll_no_manager_email(
        self,
        active_user,
        connected_user,
        agenda_item,
        enrollment_config,
        authenticated_client,
    ):
        active_user.email = ""
        active_user.save()
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (f"{connected_user.name} cannot enroll: email address required"),
                ),
                (
                    messages.ERROR,
                    ("Email address is required for enrollment in this session."),
                ),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [ConnectedUserDTO.model_validate(connected_user)],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=ConnectedUserDTO.model_validate(connected_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_ok_move_to_waiting_list(
        self, active_user, agenda_item, authenticated_client, event
    ):
        agenda_item.session.presenter = None
        agenda_item.session.save(update_fields=["presenter_id"])
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "waitlist"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Added to waiting list: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        SessionParticipation.objects.get(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )

    def test_post_cant_move_to_waiting_list(
        self, active_user, agenda_item, authenticated_client, enrollment_config
    ):
        enrollment_config.max_waitlist_sessions = 0
        enrollment_config.save()
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "waitlist"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. waitlist is not one of the available "
                        "choices."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=True,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_restrict_to_configured_users_cant_move_to_enroll(
        self, active_user, agenda_item, authenticated_client, enrollment_config, event
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        f"{active_user.name} cannot enroll: enrollment access "
                        "permission required"
                    ),
                ),
                (
                    messages.ERROR,
                    (
                        "Enrollment access permission is required for this session. "
                        "Please contact the organizers to obtain access."
                    ),
                ),
            ],
            context_data={
                **_party_context(active_user),
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=True,
                        has_time_conflict=False,
                    )
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_unknown_current_participation_status(
        self, active_user, agenda_item, authenticated_client, event
    ):
        agenda_item.session.presenter = None
        agenda_item.session.save(update_fields=["presenter_id"])
        SessionParticipation.objects.create(
            user=active_user, session=agenda_item.session, status="purchased"
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "waitlist"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Added to waiting list: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        SessionParticipation.objects.get(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.WAITING,
        )

    def test_post_unknown_current_participation_status_cant_enroll(
        self, active_user, agenda_item, authenticated_client, enrollment_config, event
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        SessionParticipation.objects.create(
            user=active_user, session=agenda_item.session, status="purchased"
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        f"{active_user.name} cannot enroll: enrollment access "
                        "permission required"
                    ),
                ),
                (
                    messages.ERROR,
                    (
                        "Enrollment access permission is required for this session. "
                        "Please contact the organizers to obtain access."
                    ),
                ),
            ],
            context_data={
                **_party_context(active_user),
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post__error_conflict_no_waitlist(
        self, active_user, agenda_item, authenticated_client, enrollment_config
    ):
        enrollment_config.max_waitlist_sessions = 0
        enrollment_config.save()
        other_session = SessionFactory(
            display_name=active_user.name,
            event=agenda_item.session.event,
            participants_limit=10,
        )
        AgendaItem.objects.create(
            session=other_session,
            space=agenda_item.space,
            start_time=agenda_item.start_time,
            end_time=agenda_item.end_time,
        )
        SessionParticipation.objects.create(
            user=active_user,
            session=other_session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. enroll is not one of the available "
                        "choices."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,  # User is not enrolled in THIS session
                        user_waiting=False,
                        has_time_conflict=True,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_restrict_to_configured_users_cant_waitlist(
        self, active_user, agenda_item, authenticated_client, event, enrollment_config
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.max_waitlist_sessions = 0
        enrollment_config.save()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. "
                        "enroll is not one of the available choices."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_connected_user_cant_enroll_no_manager_config(
        self,
        active_user,
        connected_user,
        agenda_item,
        enrollment_config,
        authenticated_client,
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        f"{connected_user.name} cannot enroll: "
                        "enrollment access permission required"
                    ),
                ),
                (
                    messages.ERROR,
                    (
                        "Enrollment access permission is required for this session. "
                        "Please contact the organizers to obtain access."
                    ),
                ),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [ConnectedUserDTO.model_validate(connected_user)],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": agenda_item.session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=ConnectedUserDTO.model_validate(connected_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_restricted_connected_user_cant_enroll(
        self,
        connected_user,
        agenda_item,
        authenticated_client,
        event,
        enrollment_config,
        active_user,
    ):
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Select a valid choice. "
                        "enroll is not one of the available choices."
                    ),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [ConnectedUserDTO.model_validate(connected_user)],
                "session": agenda_item.session,
                "event": event,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=ConnectedUserDTO.model_validate(connected_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    def test_post_no_enrollment_config(
        self, active_user, agenda_item, authenticated_client, event
    ):
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    (f"{active_user.name} cannot enroll: enrollment not available"),
                ),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            context_data={
                **_party_context(active_user),
                "connected_users": [],
                "session": agenda_item.session,
                "event": event,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
                "form": ANY,
            },
            template_name="chronology/enroll_select.html",
        )

    @pytest.mark.postgres
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.usefixtures("enrollment_config")
    def test_concurrent_enroll_does_not_overbook_capacity(self, agenda_item):
        # The `session` fixture makes `active_user` the presenter, who is always
        # skipped as the host, so both contenders must be fresh non-presenters.
        session = agenda_item.session
        session.participants_limit = 1
        session.save(update_fields=["participants_limit"])

        contenders = []
        for index in range(2):
            user = UserFactory(
                username=f"contender{index}",
                email=f"contender{index}@example.com",
                password=make_password(None),
            )
            client = Client()
            client.force_login(user)
            contenders.append((client, user.pk))

        url = self._get_url(session.pk, session.event.slug)
        barrier = threading.Barrier(len(contenders))

        def enroll(client, user_pk):
            barrier.wait()
            try:
                return client.post(url, data={f"user_{user_pk}": "enroll"})
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(contenders)) as pool:
            futures = [
                pool.submit(enroll, client, user_pk) for client, user_pk in contenders
            ]
            for future in futures:
                future.result()

        confirmed = SessionParticipation.objects.filter(
            session_id=session.pk, status=SessionParticipationStatus.CONFIRMED
        ).count()
        assert confirmed == 1


@pytest.mark.django_db
class TestDesiredStateRouting:
    # The full page posts one "include" checkbox per person plus the
    # enroll_mode=desired marker; the system routes each included person to a
    # confirmed seat or the waiting list. Enroll and waitlist are one intent now.
    def _url(self, session):
        return reverse(
            "web:chronology:session-enrollment",
            kwargs={"event_slug": session.event.slug, "session_id": session.pk},
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_include_with_room_confirms(
        self, staff_user, agenda_item, staff_client, event
    ):
        response = staff_client.post(
            self._url(agenda_item.session),
            data={"enroll_mode": "desired", f"user_{staff_user.id}": "include"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {staff_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        SessionParticipation.objects.get(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_include_on_full_session_waitlists_without_error(
        self, staff_user, agenda_item, staff_client, session, event
    ):
        # The key single-intent change: a full session no longer errors — the
        # included person simply lands on the waiting list.
        session.participants_limit = 1
        session.save()
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.post(
            self._url(agenda_item.session),
            data={"enroll_mode": "desired", f"user_{staff_user.id}": "include"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Added to waiting list: {staff_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        SessionParticipation.objects.get(
            user=staff_user, session=session, status=SessionParticipationStatus.WAITING
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_unchecking_an_enrolled_person_cancels(
        self, active_user, agenda_item, authenticated_client, event
    ):
        agenda_item.session.presenter = None
        agenda_item.session.save(update_fields=["presenter_id"])
        SessionParticipation.objects.create(
            user=active_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        # The box is left unchecked (omitted) — desired state is "out".
        response = authenticated_client.post(
            self._url(agenda_item.session), data={"enroll_mode": "desired"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_including_more_than_seats_confirms_first_then_waitlists(
        self,
        active_user,
        connected_user,
        agenda_item,
        authenticated_client,
        session,
        event,
    ):
        session.participants_limit = 1
        session.save()
        agenda_item.session.presenter = None
        agenda_item.session.save(update_fields=["presenter_id"])

        response = authenticated_client.post(
            self._url(agenda_item.session),
            data={
                "enroll_mode": "desired",
                f"user_{active_user.id}": "include",
                f"user_{connected_user.id}": "include",
            },
        )

        # Household order (viewer first) decides who gets the seat.
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, f"Enrolled: {active_user.name}"),
                (messages.SUCCESS, f"Added to waiting list: {connected_user.name}"),
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert (
            SessionParticipation.objects.get(user=active_user, session=session).status
            == SessionParticipationStatus.CONFIRMED
        )
        assert (
            SessionParticipation.objects.get(
                user=connected_user, session=session
            ).status
            == SessionParticipationStatus.WAITING
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_swap_out_frees_a_seat_for_someone_included(
        self, active_user, connected_user, agenda_item, authenticated_client, session
    ):
        # Uncheck the seated viewer and include the companion on a full session:
        # the freed seat is credited so the companion is confirmed, not waitlisted.
        session.participants_limit = 1
        session.save()
        agenda_item.session.presenter = None
        agenda_item.session.save(update_fields=["presenter_id"])
        SessionParticipation.objects.create(
            user=active_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            self._url(agenda_item.session),
            data={"enroll_mode": "desired", f"user_{connected_user.id}": "include"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=active_user, session=session
        ).exists()
        assert (
            SessionParticipation.objects.get(
                user=connected_user, session=session
            ).status
            == SessionParticipationStatus.CONFIRMED
        )


@pytest.mark.django_db
class TestSessionEnrollInline:
    # The event-page footer enrolls the viewer with one click via HTMX: the
    # endpoint swaps a footer fragment back instead of a full-page redirect, so
    # nothing navigates and the new state is the confirmation.
    URL_NAME = "web:chronology:session-enrollment"
    FRAGMENT = "chronology/parts/session-enroll-actions.html"

    def _url(self, session_id: int, event_slug: str) -> str:
        return reverse(
            self.URL_NAME, kwargs={"event_slug": event_slug, "session_id": session_id}
        )

    @staticmethod
    def _ctx(
        *,
        session,
        viewer_pk,
        user_enrolled=False,
        user_waiting=False,
        is_full=False,
        enroll_error="",
    ):
        return {
            "event_slug": session.event.slug,
            "session_pk": session.pk,
            "viewer_pk": viewer_pk,
            "can_act": True,
            "is_enrollment_available": True,
            "user_enrolled": user_enrolled,
            "user_waiting": user_waiting,
            "is_full": is_full,
            "is_unlimited": False,
            "enroll_error": enroll_error,
        }

    @pytest.mark.usefixtures("enrollment_config")
    def test_htmx_enroll_swaps_fragment_instead_of_redirecting(
        self, staff_user, agenda_item, staff_client
    ):
        session = agenda_item.session
        response = staff_client.post(
            self._url(session.pk, session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
            HTTP_HX_REQUEST="true",
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=self.FRAGMENT,
            context_data=self._ctx(
                session=session, viewer_pk=staff_user.id, user_enrolled=True
            ),
            messages=[(messages.SUCCESS, f"Enrolled: {staff_user.name}")],
            contains=['value="cancel"'],
            not_contains=['value="enroll"', 'value="waitlist"'],
        )
        SessionParticipation.objects.get(
            user=staff_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_htmx_cancel_swaps_back_the_enroll_button(
        self, staff_user, agenda_item, staff_client
    ):
        session = agenda_item.session
        SessionParticipation.objects.create(
            user=staff_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.post(
            self._url(session.pk, session.event.slug),
            data={f"user_{staff_user.id}": "cancel"},
            HTTP_HX_REQUEST="true",
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=self.FRAGMENT,
            context_data=self._ctx(session=session, viewer_pk=staff_user.id),
            messages=[(messages.SUCCESS, f"Cancelled: {staff_user.name}")],
            contains=['value="enroll"'],
            not_contains=['value="cancel"'],
        )
        assert not SessionParticipation.objects.filter(
            user=staff_user, session=session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_htmx_waitlist_on_full_session(self, staff_user, agenda_item, staff_client):
        session = agenda_item.session
        session.participants_limit = 1
        session.save(update_fields=["participants_limit"])
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.post(
            self._url(session.pk, session.event.slug),
            data={f"user_{staff_user.id}": "waitlist"},
            HTTP_HX_REQUEST="true",
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=self.FRAGMENT,
            context_data=self._ctx(
                session=session,
                viewer_pk=staff_user.id,
                user_waiting=True,
                is_full=True,
            ),
            messages=[(messages.SUCCESS, f"Added to waiting list: {staff_user.name}")],
            contains=["On the waiting list", 'value="cancel"'],
        )
        SessionParticipation.objects.get(
            user=staff_user, session=session, status=SessionParticipationStatus.WAITING
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_htmx_enroll_over_capacity_surfaces_error_inline(
        self, staff_user, agenda_item, staff_client
    ):
        # A racing enroll on a session that filled after the page loaded gets the
        # reason in the swapped fragment, not a lost redirect.
        session = agenda_item.session
        session.participants_limit = 1
        session.save(update_fields=["participants_limit"])
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        capacity_error = (
            "Not enough spots available. 1 spots requested, 0 available. "
            "Please use waiting list for some users."
        )

        response = staff_client.post(
            self._url(session.pk, session.event.slug),
            data={f"user_{staff_user.id}": "enroll"},
            HTTP_HX_REQUEST="true",
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=self.FRAGMENT,
            context_data=self._ctx(
                session=session,
                viewer_pk=staff_user.id,
                is_full=True,
                enroll_error=capacity_error,
            ),
            messages=[(messages.ERROR, capacity_error)],
            contains=["Not enough spots available."],
        )
        assert not SessionParticipation.objects.filter(
            user=staff_user, session=session
        ).exists()


@pytest.mark.django_db
class TestSeatProjection:
    # The page tells the viewer who gets a seat and who joins the waiting list:
    # a static seats-left line plus data attributes that drive the client-side
    # per-row projection (enroll-preview.ts) with the same seat accounting as
    # the server routing.
    URL_NAME = "web:chronology:session-enrollment"

    def _url(self, session_id: int, event_slug: str) -> str:
        return reverse(
            self.URL_NAME, kwargs={"event_slug": event_slug, "session_id": session_id}
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_seats_left_line_and_projection_scaffolding(
        self, agenda_item, staff_client
    ):
        session = agenda_item.session
        session.participants_limit = 2
        session.save(update_fields=["participants_limit"])
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.get(self._url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = " ".join(response.content.decode().split())
        assert "There is 1 seat left" in content
        assert 'data-seats-left="1"' in content
        assert "data-enroll-preview" in content
        assert 'data-msg-seat="Gets a seat"' in content
        assert 'data-msg-wait="Joins the waiting list"' in content
        assert 'data-msg-leave="Will leave the session"' in content
        assert 'data-current-in="0"' in content
        assert 'data-occupies-seat="0"' in content
        assert "data-seat-hint" in content

    @pytest.mark.usefixtures("enrollment_config")
    def test_full_session_says_everyone_joins_the_waiting_list(
        self, agenda_item, staff_client
    ):
        session = agenda_item.session
        session.participants_limit = 1
        session.save(update_fields=["participants_limit"])
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.get(self._url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = " ".join(response.content.decode().split())
        assert (
            "The session is full — everyone you add joins the waiting list." in content
        )
        assert 'data-seats-left="0"' in content

    @pytest.mark.usefixtures("enrollment_config")
    def test_unlimited_session_has_no_seat_counter(self, agenda_item, staff_client):
        session = agenda_item.session
        session.participants_limit = 0
        session.save(update_fields=["participants_limit"])

        response = staff_client.get(self._url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = " ".join(response.content.decode().split())
        assert "Tick everyone who should take part." in content
        assert "data-seats-left" not in content

    @pytest.mark.usefixtures("enrollment_config")
    def test_enrolled_viewer_row_occupies_a_seat(
        self, staff_user, agenda_item, staff_client
    ):
        session = agenda_item.session
        SessionParticipation.objects.create(
            user=staff_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.get(self._url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = " ".join(response.content.decode().split())
        assert 'data-current-in="1"' in content
        assert 'data-occupies-seat="1"' in content

    @pytest.mark.usefixtures("enrollment_config")
    def test_waiting_viewer_row_frees_no_seat(
        self, staff_user, agenda_item, staff_client
    ):
        # A waiting-list place is not a seat: unticking it must not credit the
        # projection with a freed seat, mirroring OCCUPYING_PARTICIPATION_STATUSES.
        session = agenda_item.session
        SessionParticipation.objects.create(
            user=staff_user, session=session, status=SessionParticipationStatus.WAITING
        )

        response = staff_client.get(self._url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = " ".join(response.content.decode().split())
        assert 'data-current-in="1"' in content
        assert 'data-occupies-seat="0"' in content


@pytest.mark.django_db
class TestDesiredStateEdgeCases:
    URL_NAME = "web:chronology:session-enrollment"

    def _url(self, session_id: int, event_slug: str) -> str:
        return reverse(
            self.URL_NAME, kwargs={"event_slug": event_slug, "session_id": session_id}
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_min_age_shows_in_the_meta_strip(self, agenda_item, staff_client):
        session = agenda_item.session
        session.min_age = 16
        session.save(update_fields=["min_age"])

        response = staff_client.get(self._url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
            contains=["16+"],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_htmx_invalid_value_surfaces_error_in_fragment(
        self, staff_user, agenda_item, staff_client
    ):
        response = staff_client.post(
            self._url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{staff_user.id}": "bogus"},
            HTTP_HX_REQUEST="true",
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/parts/session-enroll-actions.html",
            context_data=ANY,
            messages=[
                (messages.ERROR, f"Invalid choice for {staff_user.name}: bogus"),
                (messages.WARNING, "Please review the enrollment options below."),
            ],
            contains=["Invalid choice"],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_checked_box_for_already_enrolled_person_is_a_no_op(
        self, staff_user, agenda_item, staff_client
    ):
        # Desired state matches reality -> nothing to do, and the warning says
        # so instead of scolding about "selecting a user".
        SessionParticipation.objects.create(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.post(
            self._url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={"enroll_mode": "desired", f"user_{staff_user.id}": "include"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=self._url(agenda_item.session.pk, agenda_item.session.event.slug),
            messages=[(messages.WARNING, "No changes.")],
        )
        assert SessionParticipation.objects.filter(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        ).exists()

    def test_full_session_include_without_waitlist_allowance_is_skipped(
        self, staff_user, agenda_item, staff_client, enrollment_config
    ):
        # The config allows enrolling but no waiting list at all; on a full
        # session the desired-state routing has nowhere to put the person, so
        # the include is skipped rather than erroring.
        enrollment_config.max_waitlist_sessions = 0
        enrollment_config.save()
        session = agenda_item.session
        session.participants_limit = 1
        session.save(update_fields=["participants_limit"])
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.post(
            self._url(session.pk, session.event.slug),
            data={"enroll_mode": "desired", f"user_{staff_user.id}": "include"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=self._url(session.pk, session.event.slug),
            messages=[(messages.WARNING, "No changes.")],
        )
        assert not SessionParticipation.objects.filter(
            user=staff_user, session=session
        ).exists()


@pytest.mark.django_db
class TestOutcomeStatedCta:
    # Luma-style registration: the solo viewer's box starts ticked and the
    # panel's primary action states the outcome, so joining is one click.
    URL_NAME = "web:chronology:session-enrollment"

    def _url(self, session_id: int, event_slug: str) -> str:
        return reverse(
            self.URL_NAME, kwargs={"event_slug": event_slug, "session_id": session_id}
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_solo_viewer_is_prechecked_and_cta_says_join(
        self, staff_user, agenda_item, staff_client
    ):
        response = staff_client.get(
            self._url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
            contains=["Join this session"],
            not_contains=["Save changes"],
        )
        content = " ".join(response.content.decode().split())
        assert "checked" in input_tag(content, staff_user.pk)

    @pytest.mark.usefixtures("enrollment_config")
    def test_full_session_cta_says_join_the_waiting_list(
        self, agenda_item, staff_client
    ):
        session = agenda_item.session
        session.participants_limit = 1
        session.save(update_fields=["participants_limit"])
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.get(self._url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
            contains=["Join the waiting list"],
            not_contains=["Join this session"],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_enrolled_viewer_gets_save_changes(
        self, staff_user, agenda_item, staff_client
    ):
        SessionParticipation.objects.create(
            user=staff_user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = staff_client.get(
            self._url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
            contains=["Save changes"],
            not_contains=["Join this session"],
        )
