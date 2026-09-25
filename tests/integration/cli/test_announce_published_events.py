from datetime import UTC, datetime, timedelta

from django.core.management import call_command
from django.urls import reverse

from ludamus.links.db.django.models import Notification, SphereSubscription
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import EventFactory, UserFactory


def _published_event(sphere, *, published_ago=timedelta(minutes=5)):
    start = datetime.now(UTC) + timedelta(days=30)
    return EventFactory(
        sphere=sphere,
        start_time=start,
        end_time=start + timedelta(hours=8),
        publication_time=datetime.now(UTC) - published_ago,
        subscribers_announced_at=None,
    )


class TestAnnouncePublishedEvents:
    def test_tells_subscribers_about_a_newly_published_event(
        self,
        non_root_sphere,
        active_user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        event = _published_event(non_root_sphere)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("announce_published_events")

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [active_user.email]
        path = reverse("web:chronology:event", kwargs={"slug": event.slug})
        assert f"https://{non_root_sphere.site.domain}{path}" in mailoutbox[0].body
        notification = Notification.objects.get(recipient=active_user)
        assert notification.kind == NotificationKind.SPHERE_EVENT_PUBLISHED.value
        assert non_root_sphere.name in notification.title
        event.refresh_from_db()
        assert event.subscribers_announced_at is not None

    def test_runs_twice_without_announcing_twice(
        self,
        non_root_sphere,
        active_user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        _published_event(non_root_sphere)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("announce_published_events")
            call_command("announce_published_events")

        assert len(mailoutbox) == 1

    def test_leaves_an_unpublished_event_alone(
        self,
        non_root_sphere,
        active_user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        event = _published_event(non_root_sphere)
        event.publication_time = datetime.now(UTC) + timedelta(days=1)
        event.save(update_fields=["publication_time"])

        with django_capture_on_commit_callbacks(execute=True):
            call_command("announce_published_events")

        assert mailoutbox == []
        event.refresh_from_db()
        assert event.subscribers_announced_at is None

    def test_stamps_an_event_whose_sphere_nobody_follows(
        self, non_root_sphere, mailoutbox, django_capture_on_commit_callbacks
    ):
        # Otherwise the first subscriber would be greeted with a backlog.
        event = _published_event(non_root_sphere)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("announce_published_events")

        assert mailoutbox == []
        event.refresh_from_db()
        assert event.subscribers_announced_at is not None

    def test_notifies_a_subscriber_without_an_email_address_in_app_only(
        self, non_root_sphere, mailoutbox, django_capture_on_commit_callbacks
    ):
        quiet = UserFactory(username="no-email", email="")
        SphereSubscription.objects.create(sphere=non_root_sphere, user=quiet)
        _published_event(non_root_sphere)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("announce_published_events")

        assert mailoutbox == []
        assert Notification.objects.filter(recipient=quiet).exists()
