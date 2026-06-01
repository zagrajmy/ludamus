from http import HTTPStatus
from unittest.mock import ANY, Mock, patch

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    AgendaItem,
    EnrollmentConfig,
    SessionParticipation,
    SessionParticipationStatus,
    UserEnrollmentConfig,
)
from ludamus.adapters.web.django.entities import SessionUserParticipationData
from ludamus.pacts import UserDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    AreaFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_response


class TestSessionEnrollPageView:
    URL_NAME = "web:chronology:session-enrollment"

    def _get_url(self, session_id: int) -> str:
        return reverse(self.URL_NAME, kwargs={"session_id": session_id})

    def test_get_get_ok(self, active_user, authenticated_client, agenda_item):
        response = authenticated_client.get(self._get_url(agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "connected_users": [],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
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

    def test_get_error_404(self, authenticated_client):
        response = authenticated_client.get(self._get_url(17))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url="/",
        )

    def test_get_unscheduled_session_rejected(
        self, authenticated_client, pending_session
    ):
        response = authenticated_client.get(self._get_url(pending_session.pk))

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
        response = authenticated_client.post(self._get_url(agenda_item.session.pk))

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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
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
        response = authenticated_client.post(self._get_url(agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "Please select at least one user to enroll.")],
            url=self._get_url(agenda_item.session.pk),
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_ok(self, staff_user, agenda_item, staff_client, event):
        response = staff_client.post(
            self._get_url(agenda_item.session.pk),
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
            self._get_url(agenda_item.session.pk),
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
            self._get_url(agenda_item.session.pk),
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
            self._get_url(agenda_item.session.pk),
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
            self._get_url(agenda_item.session.pk),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    f"Enrolled: {connected_user.name} (promoted from waiting list)",
                ),
                (messages.SUCCESS, f"Cancelled: {active_user.name}"),
            ],
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
    def test_post__error_conflict(
        self, active_user, agenda_item, authenticated_client, event
    ):
        other_session = SessionFactory(
            display_name=active_user.name, sphere=event.sphere, participants_limit=10
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
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
            self._get_url(agenda_item.session.pk),
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
                "web:chronology:session-enrollment", kwargs={"session_id": session.id}
            ),
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_connected_user_inactive(
        self, agenda_item, authenticated_client, session, connected_user
    ):
        connected_user.is_active = False
        connected_user.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "Please select at least one user to enroll.")],
            url=reverse(
                "web:chronology:session-enrollment", kwargs={"session_id": session.id}
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
            self._get_url(agenda_item.session.pk),
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
            url=f"/chronology/event/{proposal_category.event.slug}/",
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    @staticmethod
    def test_post_time_conflict_skipped(authenticated_client, active_user, event):
        area = AreaFactory(venue__event=event)
        space1 = SpaceFactory(area=area)
        space2 = SpaceFactory(area=area)
        time_slot = TimeSlotFactory(event=event)

        session1 = SessionFactory(sphere=event.sphere)
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

        session2 = SessionFactory(sphere=event.sphere)
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
                    kwargs={"session_id": session2.id},
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
            url=f"/chronology/event/{event.slug}/",
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=session2
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_no_user_selected(self, authenticated_client, agenda_item):
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk), data={}  # No user selections
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "Please select at least one user to enroll.")],
            url=reverse(
                "web:chronology:session-enrollment",
                kwargs={"session_id": agenda_item.session.id},
            ),
        )

    def test_post_restrict_to_configured_users(
        self, staff_user, agenda_item, staff_client, event, enrollment_config
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk),
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
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
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
            self._get_url(agenda_item.session.pk),
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
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
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
            self._get_url(agenda_item.session.pk),
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
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
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
        connected_user.manager = staff_user
        connected_user.save()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=staff_user.email,
            allowed_slots=1,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = staff_client.post(
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [UserDTO.model_validate(connected_user)],
                "session": agenda_item.session,
                "event": event,
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(staff_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(connected_user),
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
            self._get_url(agenda_item.session.pk),
            data={f"user_{staff_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {staff_user.name}")],
            url=f"/chronology/event/{event.slug}/",
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
        connected_user.manager = staff_user
        connected_user.save()
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [UserDTO.model_validate(connected_user)],
                "session": agenda_item.session,
                "event": event,
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(staff_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(connected_user),
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
            self._get_url(agenda_item.session.pk),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    f"Enrolled: {connected_user.name} (promoted from waiting list)",
                ),
                (messages.SUCCESS, f"Cancelled: {active_user.name}"),
            ],
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
            self._get_url(agenda_item.session.pk),
            data={f"user_{active_user.id}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    f"Enrolled: {staff_user.name} (promoted from waiting list)",
                ),
                (messages.SUCCESS, f"Cancelled: {active_user.name}"),
            ],
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
            self._get_url(agenda_item.session.pk),
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
            self._get_url(agenda_item.session.pk),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"Enrolled: {connected_user.name}")],
            url=f"/chronology/event/{event.slug}/",
        )

    def test_post_cant_join_waitlist(
        self, active_user, agenda_item, enrollment_config, authenticated_client
    ):
        enrollment_config.max_waitlist_sessions = 0
        enrollment_config.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [UserDTO.model_validate(connected_user)],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(connected_user),
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [UserDTO.model_validate(connected_user)],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(connected_user),
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
            self._get_url(agenda_item.session.pk),
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
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
            self._get_url(agenda_item.session.pk),
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
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
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
            self._get_url(agenda_item.session.pk),
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
            self._get_url(agenda_item.session.pk),
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
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
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
        self, active_user, agenda_item, authenticated_client, enrollment_config, event
    ):
        enrollment_config.max_waitlist_sessions = 0
        enrollment_config.save()
        other_session = SessionFactory(
            display_name=active_user.name, sphere=event.sphere, participants_limit=10
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
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
            self._get_url(agenda_item.session.pk),
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
                "session": agenda_item.session,
                "event": event,
                "connected_users": [],
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [UserDTO.model_validate(connected_user)],
                "event": agenda_item.space.area.venue.event,
                "form": ANY,
                "session": agenda_item.session,
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(connected_user),
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
    ):
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=connected_user.manager.email,
            allowed_slots=0,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        response = authenticated_client.post(
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [UserDTO.model_validate(connected_user)],
                "session": agenda_item.session,
                "event": event,
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(connected_user.manager),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(connected_user),
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
            self._get_url(agenda_item.session.pk),
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
                "connected_users": [],
                "session": agenda_item.session,
                "event": event,
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
