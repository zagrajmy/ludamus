from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.gates.web.django.panel import settings_tab_urls
from ludamus.links.db.django.models import EventProposalSettings, ProposalCategory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


class TestEventProposalSettingsPageViewGet:
    @staticmethod
    def get_url(event):
        return reverse("panel:event-proposal-settings", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_ok_for_sphere_manager(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-settings.html",
            context_data={
                **panel_context(event, active_nav="settings"),
                "active_tab": "proposals",
                "tab_urls": settings_tab_urls(event.slug),
                "form": ANY,
            },
        )

    def test_redirects_on_invalid_slug(self, panel_client):
        url = reverse("panel:event-proposal-settings", kwargs={"slug": "bad-slug"})

        response = panel_client.get(url)

        assert_event_not_found(response)


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

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={})

        assert_not_a_manager(response)

    def test_redirects_on_invalid_slug(self, panel_client):
        url = reverse("panel:event-proposal-settings", kwargs={"slug": "bad-slug"})

        response = panel_client.post(url, data={})

        assert_event_not_found(response)

    def test_error_on_invalid_datetime(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event), data={"proposal_start_time": "not-a-date"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Enter a valid date/time.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )

    def test_saves_proposal_description(self, panel_client, event):
        response = panel_client.post(
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

    def test_saves_allow_anonymous_proposals(self, panel_client, event):
        response = panel_client.post(
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
        self, panel_client, event
    ):
        EventProposalSettings.objects.create(
            event=event, allow_anonymous_proposals=True
        )

        response = panel_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        settings = EventProposalSettings.objects.get(event=event)
        assert settings.allow_anonymous_proposals is False

    def test_saves_proposal_dates(self, panel_client, event):
        response = panel_client.post(
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

    def test_clears_proposal_dates(self, panel_client, event):
        response = panel_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/proposals/",
        )
        event.refresh_from_db()
        assert event.proposal_start_time is None
        assert event.proposal_end_time is None

    def test_applies_dates_to_all_categories(self, panel_client, event):
        cat1 = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        cat2 = ProposalCategory.objects.create(
            event=event, name="Board Games", slug="board-games"
        )

        response = panel_client.post(
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

    def test_does_not_apply_dates_without_checkbox(self, panel_client, event):
        cat = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        panel_client.post(
            self.get_url(event),
            data={
                "proposal_start_time": "2026-04-01T10:00",
                "proposal_end_time": "2026-04-15T18:00",
            },
        )

        cat.refresh_from_db()
        assert cat.start_time is None
        assert cat.end_time is None
