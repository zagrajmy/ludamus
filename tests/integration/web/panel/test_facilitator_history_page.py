from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, FacilitatorChangeLog
from ludamus.pacts import EventDTO, FacilitatorChangeLogDTO
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
        "active_nav": "facilitators",
    }


def _tab_urls(event, facilitator_slug):
    return {
        "details": reverse(
            "panel:facilitator-detail",
            kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
        ),
        "history": reverse(
            "panel:facilitator-history",
            kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
        ),
    }


class TestFacilitatorHistoryPageView:
    """Tests for /panel/event/<slug>/facilitators/<slug>/history/ page."""

    @staticmethod
    def get_url(event, facilitator_slug):
        return reverse(
            "panel:facilitator-history",
            kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
        )

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event, "alice")

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event, "alice"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_when_facilitator_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event, "ghost"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    def test_renders_only_this_facilitators_logs(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        bob = Facilitator.objects.create(
            event=event, display_name="Bob", slug="bob", user=None
        )
        log = FacilitatorChangeLog.objects.create(
            event=event,
            facilitator=alice,
            user=active_user,
            changes=[
                {"field": "internal_comment", "field_id": None, "old": "", "new": "VIP"}
            ],
        )
        FacilitatorChangeLog.objects.create(
            event=event,
            facilitator=bob,
            user=active_user,
            changes=[
                {"field": "internal_comment", "field_id": None, "old": "", "new": "X"}
            ],
        )

        response = authenticated_client.get(self.get_url(event, "alice"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-history.html",
            context_data={
                **_base_context(event),
                "active_tab": "history",
                "tab_urls": _tab_urls(event, "alice"),
                "facilitator_name": "Alice",
                "logs": [
                    FacilitatorChangeLogDTO(
                        pk=log.pk,
                        event_id=event.pk,
                        facilitator_id=alice.pk,
                        facilitator_name="Alice",
                        user_id=active_user.pk,
                        user_name=active_user.name,
                        changes=[
                            {
                                "field": "internal_comment",
                                "field_id": None,
                                "old": "",
                                "new": "VIP",
                            }
                        ],
                        creation_time=log.creation_time,
                    )
                ],
                "field_names": {},
            },
            contains=["Alice"],
        )

    def test_renders_empty_history(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.get(self.get_url(event, "alice"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-history.html",
            context_data={
                **_base_context(event),
                "active_tab": "history",
                "tab_urls": _tab_urls(event, "alice"),
                "facilitator_name": "Alice",
                "logs": [],
                "field_names": {},
            },
            contains="No changes recorded yet.",
        )
