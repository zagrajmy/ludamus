from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import ProposalCategory, Session
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


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

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_deletes_category_when_no_proposals(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        category_pk = category.pk

        response = authenticated_client.post(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type deleted successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert not ProposalCategory.objects.filter(pk=category_pk).exists()

    def test_post_error_when_proposals_exist(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        Session.objects.create(
            event=event,
            category=category,
            sphere=sphere,
            presenter=active_user,
            display_name=active_user.username,
            title="Test Proposal",
            slug="test-proposal",
            status="pending",
            participants_limit=6,
        )

        response = authenticated_client.post(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "Cannot delete session type with existing proposals.")
            ],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert ProposalCategory.objects.filter(pk=category.pk).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:cfp-delete",
            kwargs={"event_slug": "nonexistent", "category_slug": "any"},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_category_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:cfp-delete",
            kwargs={"event_slug": event.slug, "category_slug": "nonexistent"},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session type not found.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )

    def test_get_not_allowed(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)
