from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import ProposalCategory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


class TestCFPCreatePageView:
    """Tests for /panel/event/<slug>/cfp/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:cfp-create", kwargs={"slug": event.slug})

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_ok_for_sphere_manager(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-create.html",
            context_data={**panel_context(event, active_nav="cfp"), "form": ANY},
        )

    def test_get_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:cfp-create", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={"name": "RPG Sessions"})

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event), data={"name": "RPG Sessions"}
        )

        assert_not_a_manager(response)

    def test_post_creates_category_for_sphere_manager(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={"name": "RPG Sessions"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Category created successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert ProposalCategory.objects.filter(
            event=event, name="RPG Sessions"
        ).exists()

    def test_post_with_create_and_configure_redirects_to_edit_page(
        self, panel_client, event
    ):
        response = panel_client.post(
            self.get_url(event),
            data={"name": "RPG Sessions", "action": "create_and_configure"},
        )

        category = ProposalCategory.objects.get(event=event, name="RPG Sessions")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Category created successfully.")],
            url=f"/panel/event/{event.slug}/cfp/{category.slug}/",
        )

    def test_post_generates_slug_from_name(self, panel_client, event):
        panel_client.post(self.get_url(event), data={"name": "Board Games & Workshops"})

        category = ProposalCategory.objects.get(event=event)
        assert category.slug == "board-games-workshops"

    def test_post_error_on_empty_name_rerenders_form(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={})

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-create.html",
            context_data={**panel_context(event, active_nav="cfp"), "form": ANY},
        )
        assert not ProposalCategory.objects.filter(event=event).exists()

    def test_post_generates_unique_slug_on_collision(self, panel_client, event):
        ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        panel_client.post(self.get_url(event), data={"name": "RPG Sessions"})

        categories = ProposalCategory.objects.filter(event=event)
        assert categories.count() == 1 + 1  # existing + new
        new_category = categories.exclude(slug="rpg-sessions").first()
        assert new_category.slug.startswith("rpg-sessions-")

    def test_post_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:cfp-create", kwargs={"slug": "nonexistent"})

        response = panel_client.post(url, data={"name": "RPG Sessions"})

        assert_event_not_found(response)
