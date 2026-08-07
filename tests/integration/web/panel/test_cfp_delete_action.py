from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import ProposalCategory, Session
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
)


class TestCFPDeleteActionView:
    """Tests for /panel/event/<slug>/cfp/<category_slug>/do/delete action."""

    @staticmethod
    def get_url(event, category):
        return reverse(
            "panel:cfp-delete",
            kwargs={"event_slug": event.slug, "category_slug": category.slug},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        url = self.get_url(event, category)

        response = client.post(url)

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(self.get_url(event, category))

        assert_not_a_manager(response)

    def test_post_deletes_category_when_no_proposals(self, panel_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        category_pk = category.pk

        response = panel_client.post(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Category deleted successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert not ProposalCategory.objects.filter(pk=category_pk).exists()

    def test_post_error_when_proposals_exist(self, panel_client, active_user, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.username,
            title="Test Proposal",
            slug="test-proposal",
            status="pending",
            participants_limit=6,
        )

        response = panel_client.post(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "Cannot delete category with existing proposals.")
            ],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert ProposalCategory.objects.filter(pk=category.pk).exists()

    def test_post_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse(
            "panel:cfp-delete",
            kwargs={"event_slug": "nonexistent", "category_slug": "any"},
        )

        response = panel_client.post(url)

        assert_event_not_found(response)

    def test_post_redirects_on_invalid_category_slug(self, panel_client, event):
        url = reverse(
            "panel:cfp-delete",
            kwargs={"event_slug": event.slug, "category_slug": "nonexistent"},
        )

        response = panel_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Category not found.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )

    def test_get_not_allowed(self, panel_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = panel_client.get(self.get_url(event, category))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)
