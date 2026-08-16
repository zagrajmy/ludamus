"""Integration tests for /panel/event/<slug>/facilitators/do/bulk-action."""

from datetime import UTC, datetime
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.chronology.panel.views import (
    facilitators as facilitators_views,
)
from ludamus.gates.web.django.chronology.panel.views.facilitators import (
    BULK_FACILITATOR_ACTIONS,
)
from ludamus.links.db.django.models import Facilitator
from tests.integration.conftest import ProposalCategoryFactory, SessionFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
_DELETED_AT = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
_HAS_SESSIONS_ERROR = (
    "This facilitator is named on sessions, deleted ones included. Remove them"
    " from those sessions first."
)


# The state the selected facilitator has to be in for each action to apply.
# A new entry in `BULK_FACILITATOR_ACTIONS` KeyErrors here until it is listed.
_ACTION_NEEDS_DELETED = {
    "delete": None,
    "restore": _DELETED_AT,
    "mark-guest": None,
    "merge": None,
}


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

    @pytest.mark.parametrize("action", BULK_FACILITATOR_ACTIONS)
    def test_post_handles_every_offered_action(
        self, authenticated_client, active_user, sphere, event, action
    ):
        # An action added to the tuple without a branch in `_apply` used to
        # restore the whole selection and report success. Now it fails here.
        sphere.managers.add(active_user)
        _make_facilitator(event, "alice", deleted_at=_ACTION_NEEDS_DELETED[action])

        response = authenticated_client.post(
            self.get_url(event), {"action": action, "facilitator_slugs": ["alice"]}
        )

        if action == "merge":
            expected_url = (
                reverse("panel:facilitator-merge", kwargs={"slug": event.slug})
                + "?facilitator_slugs=alice"
            )
            expected_messages = ()
        else:
            expected_url = reverse("panel:facilitators", kwargs={"slug": event.slug})
            expected_messages = ((messages.SUCCESS, "1 facilitator updated."),)
        assert_response(
            response, HTTPStatus.FOUND, messages=expected_messages, url=expected_url
        )

    def test_post_raises_for_an_offered_action_without_a_branch(
        self, authenticated_client, active_user, sphere, event, monkeypatch
    ):
        # The state the offer list and `_apply` disagree on: the action passes
        # the membership check and then finds no branch.
        sphere.managers.add(active_user)
        _make_facilitator(event, "alice")
        monkeypatch.setattr(
            facilitators_views,
            "BULK_FACILITATOR_ACTIONS",
            (*BULK_FACILITATOR_ACTIONS, "teleport"),
        )

        with pytest.raises(
            ValueError, match="unhandled bulk facilitator action: 'teleport'"
        ):
            authenticated_client.post(
                self.get_url(event),
                {"action": "teleport", "facilitator_slugs": ["alice"]},
            )

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
                (messages.ERROR, f"1 facilitator was skipped: {_HAS_SESSIONS_ERROR}"),
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

        response = authenticated_client.post(
            self.get_url(event),
            {"action": "delete", "facilitator_slugs": ["alice"], "next": next_url},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "1 facilitator updated.")],
            url=next_url,
        )

    def test_post_rejects_offsite_next_url(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "alice", deleted_at=_DELETED_AT)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "action": "restore",
                "facilitator_slugs": ["alice"],
                "next": "https://evil.example/",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "1 facilitator updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
