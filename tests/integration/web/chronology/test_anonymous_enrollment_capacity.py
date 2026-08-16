from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    SessionParticipation,
    SessionParticipationStatus,
)
from tests.integration.conftest import EnrollmentConfigFactory
from tests.integration.utils import assert_response


def test_post_waitlists_at_open_window_capacity(
    *, agenda_item, anonymous_user_factory, client, sphere
) -> None:
    event = agenda_item.session.event
    now = datetime.now(UTC)
    EnrollmentConfigFactory(
        event=event,
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        percentage_slots=100,
        restrict_to_configured_users=True,
        allow_anonymous_enrollment=False,
    )
    EnrollmentConfigFactory(
        event=event,
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        percentage_slots=20,
        restrict_to_configured_users=False,
        allow_anonymous_enrollment=True,
    )
    session = agenda_item.session
    session.participants_limit = 100
    session.save()
    SessionParticipation.objects.bulk_create(
        [
            SessionParticipation(
                session=session,
                user=anonymous_user_factory(),
                status=SessionParticipationStatus.CONFIRMED,
            )
            for _ in range(20)
        ]
    )
    user = anonymous_user_factory()
    django_session = client.session
    django_session["anonymous_enrollment_active"] = True
    django_session["anonymous_site_id"] = sphere.site.id
    django_session["anonymous_event_id"] = event.id
    django_session["anonymous_user_code"] = user.slug.split("_")[1]
    django_session.save()

    response = client.post(
        reverse(
            "web:chronology:session-enrollment-anonymous",
            kwargs={"event_slug": event.slug, "session_id": session.id},
        ),
        data={"name": "late"},
    )

    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[
            (
                messages.SUCCESS,
                (
                    "Session is full. You have been added to the waiting list for: "
                    f"{session.title}"
                ),
            )
        ],
        url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
    )
    assert (
        SessionParticipation.objects.get(session=session, user=user).status
        == SessionParticipationStatus.WAITING
    )
