"""Integration tests for /panel/event/<slug>/proposals/create/ page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Facilitator, ProposalCategory, Session
from ludamus.pacts import EventDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "proposals",
    }


class TestProposalCreatePageView:
    """Tests for /panel/event/<slug>/proposals/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:proposal-create", kwargs={"slug": event.slug})

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:proposal-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={**_base_context(event), "form": ANY},
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={})

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
        url = reverse("panel:proposal-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_creates_session_with_unique_slug_on_collision(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        Session.objects.create(
            event=event,
            category=category,
            presenter=None,
            display_name="Host",
            title="Existing Session",
            slug="my-new-session",
            participants_limit=0,
            status="pending",
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "My New Session",
                "display_name": "Test Host",
                "description": "",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        new_session = Session.objects.get(title="My New Session", status="pending")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert new_session.slug != "my-new-session"

    def test_post_creates_session_with_facilitator_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "My New Session",
                "display_name": "Test Host",
                "description": "A great session",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        new_session = Session.objects.get(title="My New Session", status="pending")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert list(new_session.facilitators.values_list("pk", flat=True)) == [
            facilitator.pk
        ]

    def test_post_without_facilitator_shows_error(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "category_id": category.pk,
                "title": "No Facilitator",
                "display_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={**_base_context(event), "form": ANY},
        )
        assert response.context["form"].errors
        assert not Session.objects.filter(title="No Facilitator").exists()

    def test_post_ignores_facilitator_from_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        other_event = EventFactory(sphere=sphere)
        foreign = Facilitator.objects.create(
            event=other_event, display_name="Bob", slug="bob", user=None
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [foreign.pk],
                "category_id": category.pk,
                "title": "Foreign Facilitator",
                "display_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={
                **_base_context(event),
                "events": [
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
                "form": ANY,
            },
        )
        assert response.context["form"].errors
        assert not Session.objects.filter(title="Foreign Facilitator").exists()

    def test_post_shows_errors_on_invalid_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = authenticated_client.post(
            self.get_url(event),
            data={"category_id": "", "title": "", "display_name": ""},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-create.html",
            context_data={**_base_context(event), "form": ANY},
        )
        assert response.context["form"].errors
