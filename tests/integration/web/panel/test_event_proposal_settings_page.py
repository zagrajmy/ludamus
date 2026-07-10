from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.adapters.db.django.models import EventProposalSettings, ProposalCategory
from ludamus.pacts import EventDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestEventProposalSettingsPageViewGet:
    @staticmethod
    def get_url(event):
        return reverse("panel:event-proposal-settings", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-settings.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": response.context["is_proposal_active"],
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "settings",
                "active_tab": "proposals",
                "tab_urls": response.context["tab_urls"],
                "form": ANY,
            },
        )

    def test_redirects_on_invalid_slug(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        url = reverse("panel:event-proposal-settings", kwargs={"slug": "bad-slug"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )


class TestEventProposalSettingsPageViewPost:
    @staticmethod
    def get_url(event):
        return reverse("panel:event-proposal-settings", kwargs={"slug": event.slug})

    @staticmethod
    def _post_data(event, **overrides):
        data = {}
        if event.proposal_start_time:
            data["proposal_start_time"] = event.proposal_start_time.strftime(
                "%Y-%m-%dT%H:%M"
            )
        if event.proposal_end_time:
            data["proposal_end_time"] = event.proposal_end_time.strftime(
                "%Y-%m-%dT%H:%M"
            )
        data.update(overrides)
        return data

    def test_redirects_anonymous_user(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_slug(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        url = reverse("panel:event-proposal-settings", kwargs={"slug": "bad-slug"})

        response = authenticated_client.post(url, data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_error_on_invalid_datetime(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data={"proposal_start_time": "not-a-date"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Enter a valid date/time.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )

    def test_saves_proposal_description(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event),
            data=self._post_data(event, proposal_description="Welcome to our CFP!"),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        settings = EventProposalSettings.objects.get(event=event)
        assert settings.description == "Welcome to our CFP!"

    def test_saves_allow_anonymous_proposals(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event),
            data=self._post_data(event, allow_anonymous_proposals="on"),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        settings = EventProposalSettings.objects.get(event=event)
        assert settings.allow_anonymous_proposals is True

    def test_unchecking_allow_anonymous_proposals_disables_it(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        EventProposalSettings.objects.create(
            event=event, allow_anonymous_proposals=True
        )

        response = authenticated_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        settings = EventProposalSettings.objects.get(event=event)
        assert settings.allow_anonymous_proposals is False

    def test_saves_proposal_dates(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "proposal_start_time": "2026-04-01T10:00",
                "proposal_end_time": "2026-04-15T18:00",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        event.refresh_from_db()
        assert (
            localtime(event.proposal_start_time).strftime("%Y-%m-%dT%H:%M")
            == "2026-04-01T10:00"
        )
        assert (
            localtime(event.proposal_end_time).strftime("%Y-%m-%dT%H:%M")
            == "2026-04-15T18:00"
        )

    def test_clears_proposal_dates(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        event.refresh_from_db()
        assert event.proposal_start_time is None
        assert event.proposal_end_time is None

    def test_applies_dates_to_all_categories(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        cat1 = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        cat2 = ProposalCategory.objects.create(
            event=event, name="Board Games", slug="board-games"
        )

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "proposal_start_time": "2026-04-01T10:00",
                "proposal_end_time": "2026-04-15T18:00",
                "apply_dates_to_categories": "on",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        cat1.refresh_from_db()
        cat2.refresh_from_db()
        assert (
            localtime(cat1.start_time).strftime("%Y-%m-%dT%H:%M") == "2026-04-01T10:00"
        )
        assert localtime(cat1.end_time).strftime("%Y-%m-%dT%H:%M") == "2026-04-15T18:00"
        assert (
            localtime(cat2.start_time).strftime("%Y-%m-%dT%H:%M") == "2026-04-01T10:00"
        )
        assert localtime(cat2.end_time).strftime("%Y-%m-%dT%H:%M") == "2026-04-15T18:00"

    def test_does_not_apply_dates_without_checkbox(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        cat = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        authenticated_client.post(
            self.get_url(event),
            data={
                "proposal_start_time": "2026-04-01T10:00",
                "proposal_end_time": "2026-04-15T18:00",
            },
        )

        cat.refresh_from_db()
        assert cat.start_time is None
        assert cat.end_time is None
