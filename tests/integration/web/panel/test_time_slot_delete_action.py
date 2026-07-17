from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import ProposalCategory, Session, TimeSlot
from tests.integration.conftest import EventFactory, TimeSlotFactory, UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTimeSlotDeleteActionView:
    """Tests for time-slots/<pk>/do/delete action."""

    @staticmethod
    def get_url(event, time_slot):
        return reverse(
            "panel:time-slot-delete", kwargs={"slug": event.slug, "pk": time_slot.pk}
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event, time_slot):
        url = self.get_url(event, time_slot)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(
        self, authenticated_client, event, time_slot
    ):
        response = authenticated_client.post(self.get_url(event, time_slot))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_deletes_time_slot_for_manager(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event, time_slot))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Time slot deleted successfully.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        assert not TimeSlot.objects.filter(pk=time_slot.pk).exists()

    def test_post_error_when_slot_used_in_proposal(
        self, authenticated_client, active_user, sphere, event, time_slot
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="Session", slug="session"
        )
        host = UserFactory(username="host", user_type="active")
        session = Session.objects.create(
            event=event,
            title="Test",
            slug="test",
            category=category,
            presenter=host,
            display_name=host.username,
            status="pending",
            participants_limit=10,
        )
        session.time_slots.add(time_slot)

        response = authenticated_client.post(self.get_url(event, time_slot))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Cannot delete time slot used in proposals.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        assert TimeSlot.objects.filter(pk=time_slot.pk).exists()

    def test_post_redirects_on_invalid_pk(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:time-slot-delete", kwargs={"slug": event.slug, "pk": 99999}
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Time slot not found.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, time_slot
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:time-slot-delete", kwargs={"slug": "nonexistent", "pk": time_slot.pk}
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_rejects_slot_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        other_slot = TimeSlotFactory(event=other_event)
        url = reverse(
            "panel:time-slot-delete", kwargs={"slug": event.slug, "pk": other_slot.pk}
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Time slot not found.")],
            url=f"/panel/event/{event.slug}/cfp/time-slots/",
        )
        assert TimeSlot.objects.filter(pk=other_slot.pk).exists()
