from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, FacilitatorChangeLog
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


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

        assert response.status_code == HTTPStatus.OK
        assert response.templates[0].name == "panel/facilitator-history.html"
        assert [entry.pk for entry in response.context["logs"]] == [log.pk]
        assert response.context["facilitator_name"] == "Alice"
        assert response.context["active_tab"] == "history"
        assert response.context["tab_urls"] == {
            "details": reverse(
                "panel:facilitator-detail",
                kwargs={"slug": event.slug, "facilitator_slug": "alice"},
            ),
            "history": self.get_url(event, "alice"),
        }

    def test_renders_empty_history(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.get(self.get_url(event, "alice"))

        assert response.status_code == HTTPStatus.OK
        assert response.templates[0].name == "panel/facilitator-history.html"
        assert response.context["logs"] == []
        assert "No changes recorded yet." in response.content.decode()
