"""Integration tests for /panel/event/<slug>/proposals/do/bulk-accept."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import ProposalCategory, Session
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_session(event, category, slug, **kwargs):
    defaults = {
        "event": event,
        "category": category,
        "presenter": None,
        "display_name": "Test Host",
        "title": slug,
        "slug": slug,
        "participants_limit": 5,
        "status": "pending",
    }
    defaults.update(kwargs)
    return Session.objects.create(**defaults)


class TestProposalBulkAcceptActionView:
    @staticmethod
    def get_url(event):
        return reverse("panel:proposal-bulk-accept", kwargs={"slug": event.slug})

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_accepts_selected_and_ignores_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        one = _make_session(event, category, "one")
        two = _make_session(event, category, "two", status="on_hold")
        other_event = EventFactory(sphere=sphere)
        other_category = ProposalCategory.objects.create(
            event=other_event, name="RPG", slug="rpg-other"
        )
        foreign = _make_session(other_event, other_category, "foreign")

        response = authenticated_client.post(
            self.get_url(event), {"proposal_ids": [one.pk, two.pk, foreign.pk]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Accepted 2 proposals.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        one.refresh_from_db()
        two.refresh_from_db()
        foreign.refresh_from_db()
        assert one.status == "accepted"
        assert two.status == "accepted"
        assert foreign.status == "pending"

    def test_empty_selection_reports_nothing_accepted(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), {"proposal_ids": []})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.INFO, "No proposals were accepted.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_redirect_preserves_filter_query_string(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        one = _make_session(event, category, "one")

        list_url = reverse("panel:proposals", kwargs={"slug": event.slug})
        response = authenticated_client.post(
            f"{self.get_url(event)}?status=on_hold", {"proposal_ids": [one.pk]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Accepted 1 proposal.")],
            url=f"{list_url}?status=on_hold",
        )
