"""Integration tests for /panel/event/<slug>/proposals/do/bulk-status."""

from datetime import UTC, datetime
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import ProposalCategory, Session
from tests.integration.conftest import AgendaItemFactory, EventFactory, SpaceFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
SCHEDULED_SKIPPED = (
    "1 scheduled proposal was skipped; remove it from the timetable to "
    "change its status."
)


def _make_session(event, slug, **kwargs):
    category, _ = ProposalCategory.objects.get_or_create(
        event=event, slug="rpg", defaults={"name": "RPG"}
    )
    defaults = {
        "event": event,
        "category": category,
        "presenter": None,
        "display_name": "Test Host",
        "title": f"Session {slug}",
        "slug": slug,
        "participants_limit": 5,
        "status": "pending",
    }
    defaults.update(kwargs)
    return Session.objects.create(**defaults)


class TestProposalBulkStatusActionView:
    """Tests for POST /panel/event/<slug>/proposals/do/bulk-status."""

    @staticmethod
    def get_url(event):
        return reverse("panel:proposal-bulk-status", kwargs={"slug": event.slug})

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, {"action": "accept"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), {"action": "accept"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_accepts_multiple_and_redirects_to_list(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        one = _make_session(event, "one")
        two = _make_session(event, "two", status="on_hold")

        response = authenticated_client.post(
            self.get_url(event), {"action": "accept", "proposal_ids": [one.pk, two.pk]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "2 proposals updated.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        one.refresh_from_db()
        two.refresh_from_db()
        assert one.status == "accepted"
        assert two.status == "accepted"

    def test_post_skips_scheduled_on_reject(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        plain = _make_session(event, "plain")
        scheduled = _make_session(event, "scheduled")
        AgendaItemFactory(
            session=scheduled,
            space=SpaceFactory(event=event),
            start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
        )

        response = authenticated_client.post(
            self.get_url(event),
            {"action": "reject", "proposal_ids": [plain.pk, scheduled.pk]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, "1 proposal updated."),
                (messages.WARNING, SCHEDULED_SKIPPED),
            ],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        plain.refresh_from_db()
        scheduled.refresh_from_db()
        assert plain.status == "rejected"
        assert scheduled.status == "pending"

    def test_post_reports_missing_proposals(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        mine = _make_session(event, "mine")
        other = _make_session(EventFactory(sphere=sphere), "other")

        response = authenticated_client.post(
            self.get_url(event),
            {"action": "accept", "proposal_ids": [mine.pk, other.pk, 99999]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, "1 proposal updated."),
                (messages.ERROR, "2 proposals could not be found."),
            ],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        mine.refresh_from_db()
        other.refresh_from_db()
        assert mine.status == "accepted"
        assert other.status == "pending"

    def test_post_without_selection_warns(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), {"action": "accept"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "No proposals selected.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_post_with_unknown_action_errors(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, "one")

        response = authenticated_client.post(
            self.get_url(event), {"action": "explode", "proposal_ids": [session.pk]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Unknown bulk action.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        session.refresh_from_db()
        assert session.status == "pending"

    def test_post_honors_safe_next_url(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, "one")
        next_url = (
            reverse("panel:proposals", kwargs={"slug": event.slug}) + "?status=pending"
        )

        response = authenticated_client.post(
            self.get_url(event),
            {"action": "accept", "proposal_ids": [session.pk], "next": next_url},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "1 proposal updated.")],
            url=next_url,
        )
