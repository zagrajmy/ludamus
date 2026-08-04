"""Integration tests for /panel/event/<slug>/facilitators/do/bulk-action."""

from datetime import UTC, datetime
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator
from tests.integration.conftest import ProposalCategoryFactory, SessionFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
_DELETED_AT = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def _make_facilitator(event, slug, **kwargs):
    defaults = {"display_name": slug.title(), "slug": slug, "user": None}
    defaults.update(kwargs)
    return Facilitator.objects.create(event=event, **defaults)


class TestFacilitatorBulkActionView:
    """Tests for POST /panel/event/<slug>/facilitators/do/bulk-action."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitator-bulk-action", kwargs={"slug": event.slug})

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, {"action": "delete"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), {"action": "delete"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:facilitator-bulk-action", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, {"action": "delete"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_deletes_multiple_and_redirects_to_list(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _make_facilitator(event, "alice")
        bob = _make_facilitator(event, "bob")

        response = authenticated_client.post(
            self.get_url(event),
            {"action": "delete", "facilitator_slugs": ["alice", "bob"]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "2 facilitators updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        alice.refresh_from_db()
        bob.refresh_from_db()
        assert alice.deleted_at is not None
        assert bob.deleted_at is not None

    def test_post_restores_and_marks_guest(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _make_facilitator(event, "alice", deleted_at=_DELETED_AT)

        restore = authenticated_client.post(
            self.get_url(event), {"action": "restore", "facilitator_slugs": ["alice"]}
        )
        guest = authenticated_client.post(
            self.get_url(event),
            {"action": "mark-guest", "facilitator_slugs": ["alice"]},
        )

        list_url = reverse("panel:facilitators", kwargs={"slug": event.slug})
        assert_response(
            restore,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "1 facilitator updated.")],
            url=list_url,
        )
        assert_response(
            guest,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, "1 facilitator updated."),
                (messages.SUCCESS, "1 facilitator updated."),
            ],
            url=list_url,
        )
        alice.refresh_from_db()
        assert alice.deleted_at is None
        assert alice.accreditation_type == "guest"

    def test_post_keeps_the_facilitators_that_run_sessions(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _make_facilitator(event, "alice")
        busy = _make_facilitator(event, "busy")
        SessionFactory(
            category=ProposalCategoryFactory(event=event), event=event
        ).facilitators.add(busy)

        response = authenticated_client.post(
            self.get_url(event),
            {"action": "delete", "facilitator_slugs": ["alice", "busy"]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, "1 facilitator updated."),
                (messages.ERROR, "1 facilitator runs sessions and was kept."),
            ],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        alice.refresh_from_db()
        busy.refresh_from_db()
        assert alice.deleted_at is not None
        assert busy.deleted_at is None

    def test_post_reports_missing_facilitators(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "alice")

        response = authenticated_client.post(
            self.get_url(event),
            {"action": "delete", "facilitator_slugs": ["alice", "ghost"]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, "1 facilitator updated."),
                (messages.ERROR, "1 facilitator could not be found."),
            ],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    def test_post_without_selection_warns(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), {"action": "delete"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "No facilitators selected.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    def test_post_with_unknown_action_errors(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "alice")

        response = authenticated_client.post(
            self.get_url(event), {"action": "explode", "facilitator_slugs": ["alice"]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Unknown bulk action.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    def test_post_honors_safe_next_url(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "alice")
        next_url = (
            reverse("panel:facilitators", kwargs={"slug": event.slug}) + "?deleted=true"
        )

        safe = authenticated_client.post(
            self.get_url(event),
            {"action": "delete", "facilitator_slugs": ["alice"], "next": next_url},
        )
        unsafe = authenticated_client.post(
            self.get_url(event),
            {
                "action": "restore",
                "facilitator_slugs": ["alice"],
                "next": "https://evil.example/",
            },
        )

        assert safe.url == next_url
        assert unsafe.url == reverse("panel:facilitators", kwargs={"slug": event.slug})
