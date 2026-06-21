import threading
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.db import connection
from django.test import Client
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Notification,
    SessionParticipation,
    SessionParticipationStatus,
    User,
)
from ludamus.pacts import UserDTO
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import AgendaItemFactory, EventFactory, SessionFactory
from tests.integration.utils import assert_response


def _anonymous_user_code(user: User) -> str:
    return user.slug.split("_")[1]


def _activate_anonymous_client(client, *, sphere, event, user_code: str) -> None:
    session = client.session
    session["anonymous_enrollment_active"] = True
    session["anonymous_site_id"] = sphere.site.id
    session["anonymous_event_id"] = event.id
    session["anonymous_user_code"] = user_code
    session.save()


def _prepare_anonymous_enrollable_session(enrollment_config) -> None:
    enrollment_config.allow_anonymous_enrollment = True
    enrollment_config.save()


class TestSessionEnrollmentAnonymousPageView:
    URL = "web:chronology:session-enrollment-anonymous"

    def get_url(self, session_id: int) -> str:
        return reverse(self.URL, kwargs={"session_id": session_id})

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_authenticated_user(self, authenticated_client, method, session):
        response = getattr(authenticated_client, method)(self.get_url(session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse(
                "web:chronology:session-enrollment", kwargs={"session_id": session.id}
            ),
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_get_not_active(self, client, method, session):
        response = getattr(client, method)(self.get_url(session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Anonymous enrollment is not active.")],
            url=reverse("web:index"),
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_get_different_site(self, agenda_item, client, method):
        session = client.session
        session["anonymous_enrollment_active"] = True
        session["anonymous_site_id"] = agenda_item.session.sphere.site_id + 1000
        session.save()

        response = getattr(client, method)(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "Anonymous enrollment session is not valid for this site.",
                )
            ],
            url=reverse("web:index"),
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_get_session_doesnt_exist(self, client, method, sphere):
        session = client.session
        session["anonymous_enrollment_active"] = True
        session["anonymous_site_id"] = sphere.site.id
        session.save()

        response = getattr(client, method)(self.get_url(789))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url=reverse("web:index"),
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_get_no_anonymous_user_id(
        self, agenda_item, client, method, sphere, enrollment_config
    ):
        _prepare_anonymous_enrollable_session(enrollment_config)
        session = client.session
        session["anonymous_enrollment_active"] = True
        session["anonymous_site_id"] = sphere.site.id
        session["anonymous_event_id"] = enrollment_config.event.id
        session.save()

        response = getattr(client, method)(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Anonymous session expired.")],
            url=reverse("web:index"),
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_get_anonymous_user_doesnt_exist(
        self, agenda_item, client, method, sphere, enrollment_config
    ):
        _prepare_anonymous_enrollable_session(enrollment_config)
        session = client.session
        session["anonymous_enrollment_active"] = True
        session["anonymous_site_id"] = sphere.site.id
        session["anonymous_event_id"] = enrollment_config.event.id
        session["anonymous_user_code"] = "789"
        session.save()

        response = getattr(client, method)(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Anonymous user not found.")],
            url=reverse("web:index"),
        )

    def test_get_ok(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )

        response = client.get(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "session": agenda_item.session,
                "event": agenda_item.space.area.venue.event,
                "anonymous_user": UserDTO.model_validate(user),
                "anonymous_code": user.slug.removeprefix("code_"),
                "needs_user_data": True,
                "existing_enrollment": None,
                "is_enrolled": False,
            },
            template_name="chronology/anonymous_enroll.html",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_get_not_enrollable_without_existing_enrollment(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        user = anonymous_user_factory()
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )

        response = client.get(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "No enrollment configuration is available for this session.",
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )

    def test_post_missing_name(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )

        response = client.post(self.get_url(agenda_item.session.id), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Name is required.")],
            url=reverse(
                "web:chronology:session-enrollment-anonymous",
                kwargs={"session_id": agenda_item.session.id},
            ),
        )

    def test_post_user_saved(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.save()
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        name = "johny"

        response = client.post(
            self.get_url(agenda_item.session.id), data={"name": name}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    f"Successfully enrolled in session: {agenda_item.session.title}",
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        user = User.objects.get(id=user.id)
        assert user.name == name
        assert SessionParticipation.objects.get(
            session=agenda_item.session,
            user=user,
            status=SessionParticipationStatus.CONFIRMED,
        )

    def test_post_cancel_error(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.save()
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        name = "johny"

        response = client.post(
            self.get_url(agenda_item.session.id),
            data={"name": name, "action": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "No enrollment found to cancel.")],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        user = User.objects.get(id=user.id)
        assert user.name == name

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancel_promote(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.save()
        confirmed_user = anonymous_user_factory()
        waiting_user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        SessionParticipation.objects.create(
            session=session,
            user=confirmed_user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        SessionParticipation.objects.create(
            session=session,
            user=waiting_user,
            status=SessionParticipationStatus.WAITING,
        )
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(confirmed_user),
        )

        response = client.post(
            self.get_url(session.id), data={"name": "confirmed", "action": "cancel"}
        )

        # The promotee is notified directly now; the canceller only sees their
        # own cancellation (no "stolen" promotion message).
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Successfully cancelled enrollment in session: "
                        f"{session.title}"
                    ),
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        assert not SessionParticipation.objects.filter(
            user=confirmed_user, session=session
        ).exists()
        assert SessionParticipation.objects.filter(
            user=waiting_user,
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        ).exists()
        assert Notification.objects.filter(
            recipient=waiting_user, kind=NotificationKind.WAITLIST_PROMOTED.value
        ).exists()

    @pytest.mark.postgres
    @pytest.mark.django_db(transaction=True)
    def test_concurrent_anonymous_enroll_does_not_overbook_capacity(
        self, agenda_item, anonymous_user_factory, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.participants_limit = 1
        session.save()
        _prepare_anonymous_enrollable_session(enrollment_config)

        contenders = []
        for index in range(2):
            user = anonymous_user_factory()
            client = Client()
            _activate_anonymous_client(
                client,
                sphere=sphere,
                event=enrollment_config.event,
                user_code=_anonymous_user_code(user),
            )
            contenders.append((client, user, f"contender{index}"))

        url = self.get_url(session.pk)
        barrier = threading.Barrier(len(contenders))

        def enroll(client, name):
            barrier.wait()
            try:
                return client.post(url, data={"name": name})
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(contenders)) as pool:
            futures = [
                pool.submit(enroll, client, name) for client, _user, name in contenders
            ]
            for future in futures:
                future.result()

        confirmed = SessionParticipation.objects.filter(
            session_id=session.pk, status=SessionParticipationStatus.CONFIRMED
        ).count()
        assert confirmed == 1

    def test_post_cancel_success(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.save()
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        name = "johny"

        response = client.post(
            self.get_url(agenda_item.session.id),
            data={"name": name, "action": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Successfully cancelled enrollment in session: "
                        f"{agenda_item.session.title}"
                    ),
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        user = User.objects.get(id=user.id)
        assert user.name == name
        assert not SessionParticipation.objects.all().exists()

    def test_post_cancel_waiting_does_not_free_seat(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        SessionParticipation.objects.create(
            session=session, user=user, status=SessionParticipationStatus.WAITING
        )

        response = client.post(
            self.get_url(session.id), data={"name": "johny", "action": "cancel"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    f"Successfully cancelled enrollment in session: {session.title}",
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        assert not SessionParticipation.objects.filter(
            session=session, user=user
        ).exists()

    def test_post_cancel_when_enrollment_inactive(
        self,
        agenda_item,
        anonymous_user_factory,
        client,
        sphere,
        event,
        faker,
        time_zone,
    ):
        enrollment_config = event.enrollment_configs.create(
            start_time=faker.date_time_between("-10d", "-5d", tzinfo=time_zone),
            end_time=faker.date_time_between("-4d", "-1d", tzinfo=time_zone),
            allow_anonymous_enrollment=True,
        )
        session = agenda_item.session
        user = anonymous_user_factory()
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        SessionParticipation.objects.create(
            session=session, user=user, status=SessionParticipationStatus.CONFIRMED
        )
        name = "johny"

        response = client.post(
            self.get_url(session.id), data={"name": name, "action": "cancel"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Successfully cancelled enrollment in session: "
                        f"{session.title}"
                    ),
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        assert not SessionParticipation.objects.filter(
            session=session, user=user
        ).exists()

    def test_post_conflict(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.save()
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        session2 = SessionFactory(event=agenda_item.session.event, sphere=sphere)
        AgendaItemFactory(
            session=session2,
            start_time=agenda_item.start_time,
            end_time=agenda_item.end_time,
            space__area__venue__event=agenda_item.space.area.venue.event,
        )
        SessionParticipation.objects.create(
            session=session2, user=user, status=SessionParticipationStatus.CONFIRMED
        )
        name = "johny"

        response = client.post(
            self.get_url(agenda_item.session.id), data={"name": name}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    (
                        "Cannot enroll: You are already enrolled in another session "
                        "that conflicts with this time slot."
                    ),
                )
            ],
            url=reverse(
                "web:chronology:session-enrollment-anonymous",
                kwargs={"session_id": agenda_item.session.id},
            ),
        )
        user = User.objects.get(id=user.id)
        assert user.name == name

    def test_post_session_full(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.participants_limit = 1
        session.save()
        filler_user = anonymous_user_factory()
        SessionParticipation.objects.create(
            session=session,
            user=filler_user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        name = "johny"

        response = client.post(
            self.get_url(agenda_item.session.id), data={"name": name}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Session is full. You have been added to the waiting list "
                        f"for: {agenda_item.session.title}"
                    ),
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        user = User.objects.get(id=user.id)
        assert user.name == name

    def test_post_update_waiting(
        self, agenda_item, anonymous_user_factory, client, sphere, enrollment_config
    ):
        session = agenda_item.session
        session.min_age = 12
        session.save()
        user = anonymous_user_factory()
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=user,
            status=SessionParticipationStatus.WAITING,
        )
        name = "johny"

        response = client.post(
            self.get_url(agenda_item.session.id), data={"name": name}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    f"Successfully enrolled in session: {agenda_item.session.title}",
                )
            ],
            url=reverse(
                "web:chronology:event",
                kwargs={"slug": agenda_item.space.area.venue.event.slug},
            ),
        )
        user = User.objects.get(id=user.id)
        assert user.name == name
        assert SessionParticipation.objects.get(
            session=agenda_item.session,
            user=user,
            status=SessionParticipationStatus.CONFIRMED,
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_rejects_session_from_other_event(
        self,
        agenda_item,
        anonymous_user_factory,
        client,
        method,
        sphere,
        enrollment_config,
    ):
        user = anonymous_user_factory()
        other_event = EventFactory(sphere=sphere)
        _prepare_anonymous_enrollable_session(enrollment_config)
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=other_event,
            user_code=_anonymous_user_code(user),
        )

        response = getattr(client, method)(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "Anonymous enrollment is not available for this session.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": other_event.slug}),
        )
        assert not SessionParticipation.objects.filter(
            session=agenda_item.session, user=user
        ).exists()

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_rejects_unscheduled_session(
        self,
        pending_session,
        anonymous_user_factory,
        client,
        method,
        sphere,
        enrollment_config,
    ):
        user = anonymous_user_factory()
        enrollment_config.allow_anonymous_enrollment = True
        enrollment_config.save()
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )

        response = getattr(client, method)(self.get_url(pending_session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "No enrollment configuration is available for this session.",
                )
            ],
            url=reverse(
                "web:chronology:event", kwargs={"slug": enrollment_config.event.slug}
            ),
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_rejects_session_when_event_disallows_anonymous(
        self,
        agenda_item,
        anonymous_user_factory,
        client,
        method,
        sphere,
        enrollment_config,
    ):
        user = anonymous_user_factory()
        _activate_anonymous_client(
            client,
            sphere=sphere,
            event=enrollment_config.event,
            user_code=_anonymous_user_code(user),
        )

        response = getattr(client, method)(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "No enrollment configuration is available for this session.",
                )
            ],
            url=reverse(
                "web:chronology:event", kwargs={"slug": enrollment_config.event.slug}
            ),
        )
        assert not SessionParticipation.objects.filter(
            session=agenda_item.session, user=user
        ).exists()

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_unscheduled_session_redirects_to_index_when_event_missing(
        self, pending_session, anonymous_user_factory, client, method, sphere
    ):
        user = anonymous_user_factory()
        django_session = client.session
        django_session["anonymous_enrollment_active"] = True
        django_session["anonymous_site_id"] = sphere.site.id
        django_session["anonymous_event_id"] = 9_999_999
        django_session["anonymous_user_code"] = _anonymous_user_code(user)
        django_session.save()

        response = getattr(client, method)(self.get_url(pending_session.id))

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

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_redirects_to_index_when_activated_event_unset(
        self, agenda_item, anonymous_user_factory, client, method, sphere
    ):
        user = anonymous_user_factory()
        django_session = client.session
        django_session["anonymous_enrollment_active"] = True
        django_session["anonymous_site_id"] = sphere.site.id
        django_session["anonymous_user_code"] = _anonymous_user_code(user)
        django_session.save()

        response = getattr(client, method)(self.get_url(agenda_item.session.id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "Anonymous enrollment is not available for this session.",
                )
            ],
            url="/",
        )
