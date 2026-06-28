"""Integration tests for /panel/event/<slug>/facilitators/ page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Facilitator
from ludamus.pacts import EventDTO, FacilitatorListItemDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

_PAGE_SIZE = 50
_SEED_COUNT = 60
_LAST_PAGE_COUNT = _SEED_COUNT - _PAGE_SIZE
_TOTAL_PAGES = 2


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
        "active_nav": "facilitators",
    }


class TestFacilitatorsPageView:
    """Tests for /panel/event/<slug>/facilitators/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitators", kwargs={"slug": event.slug})

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
        url = reverse("panel:facilitators", kwargs={"slug": "nonexistent"})

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

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={**_base_context(event), "facilitators": [], "page_obj": ANY},
        )

    def test_get_lists_facilitators_for_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Alice",
                        pk=response.context["facilitators"][0].pk,
                        slug="alice",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": ANY,
            },
        )

    def test_paginates_facilitators(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        for i in range(_SEED_COUNT):
            Facilitator.objects.create(
                event=event, display_name=f"F{i}", slug=f"f-{i}", user=None
            )

        page1 = authenticated_client.get(self.get_url(event))
        page2 = authenticated_client.get(self.get_url(event), {"page": "2"})

        assert len(page1.context["facilitators"]) == _PAGE_SIZE
        assert page1.context["page_obj"].paginator.num_pages == _TOTAL_PAGES
        assert len(page2.context["facilitators"]) == _LAST_PAGE_COUNT
        assert page2.context["page_obj"].number == _TOTAL_PAGES
