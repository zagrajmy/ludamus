from datetime import UTC, datetime
from http import HTTPStatus

from django.urls import reverse
from freezegun import freeze_time

from ludamus.links.db.django.models import ProposalCategory, Session
from ludamus.pacts import ProposalCategoryDTO
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    cfp_tab_urls,
    panel_context,
)


class TestCFPPageView:
    """Tests for /panel/event/<slug>/cfp/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:cfp", kwargs={"slug": event.slug})

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
            template_name="panel/cfp.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "active_tab": "types",
                "tab_urls": cfp_tab_urls(event),
                "categories": [],
                "category_stats": {},
            },
        )

    def test_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:cfp", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_returns_categories_in_context(self, panel_client, event):
        cat1 = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg"
        )
        cat2 = ProposalCategory.objects.create(
            event=event, name="Workshops", slug="workshops"
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "active_tab": "types",
                "tab_urls": cfp_tab_urls(event),
                "categories": [
                    ProposalCategoryDTO(
                        pk=cat1.pk,
                        name="RPG Sessions",
                        slug="rpg",
                        description="",
                        start_time=None,
                        end_time=None,
                        min_participants_limit=0,
                        max_participants_limit=0,
                        durations=[],
                    ),
                    ProposalCategoryDTO(
                        pk=cat2.pk,
                        name="Workshops",
                        slug="workshops",
                        description="",
                        start_time=None,
                        end_time=None,
                        min_participants_limit=0,
                        max_participants_limit=0,
                        durations=[],
                    ),
                ],
                "category_stats": {
                    cat1.pk: {"proposals_count": 0, "accepted_count": 0},
                    cat2.pk: {"proposals_count": 0, "accepted_count": 0},
                },
            },
        )

    def test_returns_empty_categories_when_none_exist(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "active_tab": "types",
                "tab_urls": cfp_tab_urls(event),
                "categories": [],
                "category_stats": {},
            },
        )

    # Status badge tests

    def test_shows_not_set_status_when_no_times(self, panel_client, event):
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = panel_client.get(self.get_url(event))

        assert b"Not set" in response.content

    @freeze_time("2025-06-15 12:00:00")
    def test_shows_closed_status_when_past(self, panel_client, event):
        ProposalCategory.objects.create(
            event=event,
            name="RPG",
            slug="rpg",
            start_time=datetime(2025, 5, 1, tzinfo=UTC),
            end_time=datetime(2025, 5, 31, tzinfo=UTC),
        )

        response = panel_client.get(self.get_url(event))

        assert b"Closed" in response.content

    @freeze_time("2025-04-15 12:00:00")
    def test_shows_upcoming_status_when_future(self, panel_client, event):
        ProposalCategory.objects.create(
            event=event,
            name="RPG",
            slug="rpg",
            start_time=datetime(2025, 5, 1, tzinfo=UTC),
            end_time=datetime(2025, 5, 31, tzinfo=UTC),
        )

        response = panel_client.get(self.get_url(event))

        assert b"Upcoming" in response.content

    @freeze_time("2025-05-15 12:00:00")
    def test_shows_active_status_when_open(self, panel_client, event):
        ProposalCategory.objects.create(
            event=event,
            name="RPG",
            slug="rpg",
            start_time=datetime(2025, 5, 1, tzinfo=UTC),
            end_time=datetime(2025, 5, 31, tzinfo=UTC),
        )

        response = panel_client.get(self.get_url(event))

        assert b"Active" in response.content

    @freeze_time("2025-05-15 12:00:00")
    def test_shows_active_status_when_only_start_time(self, panel_client, event):
        ProposalCategory.objects.create(
            event=event,
            name="RPG",
            slug="rpg",
            start_time=datetime(2025, 5, 1, tzinfo=UTC),
        )

        response = panel_client.get(self.get_url(event))

        assert b"Active" in response.content

    @freeze_time("2025-05-15 12:00:00")
    def test_shows_not_set_status_when_only_end_time_in_future(
        self, panel_client, event
    ):
        ProposalCategory.objects.create(
            event=event,
            name="RPG",
            slug="rpg",
            end_time=datetime(2025, 5, 31, tzinfo=UTC),
        )

        response = panel_client.get(self.get_url(event))

        assert b"Not set" in response.content

    # Stats display tests

    def test_shows_zero_stats_when_no_proposals(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp.html",
            context_data={
                **panel_context(event, active_nav="cfp"),
                "active_tab": "types",
                "tab_urls": cfp_tab_urls(event),
                "categories": [
                    ProposalCategoryDTO(
                        pk=category.pk,
                        name="RPG",
                        slug="rpg",
                        description="",
                        start_time=None,
                        end_time=None,
                        min_participants_limit=0,
                        max_participants_limit=0,
                        durations=[],
                    )
                ],
                "category_stats": {
                    category.pk: {"proposals_count": 0, "accepted_count": 0}
                },
            },
        )
        assert b"0 / 0" in response.content

    def test_shows_proposal_stats(self, panel_client, active_user, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        # Create 3 sessions (2 pending, 1 accepted)
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            title="Pending 1",
            slug="pending-1",
            participants_limit=5,
            status="pending",
        )
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            title="Pending 2",
            slug="pending-2",
            participants_limit=5,
            status="pending",
        )
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            title="Accepted",
            slug="accepted",
            participants_limit=5,
            status="accepted",
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp.html",
            context_data={
                **panel_context(
                    event,
                    active_nav="cfp",
                    hosts_count=1,
                    pending_proposals=1 + 1,
                    total_proposals=1 + 1 + 1,
                    total_sessions=1 + 1,
                ),
                "active_tab": "types",
                "tab_urls": cfp_tab_urls(event),
                "categories": [
                    ProposalCategoryDTO(
                        pk=category.pk,
                        name="RPG",
                        slug="rpg",
                        description="",
                        start_time=None,
                        end_time=None,
                        min_participants_limit=0,
                        max_participants_limit=0,
                        durations=[],
                    )
                ],
                "category_stats": {
                    category.pk: {"proposals_count": 1 + 1 + 1, "accepted_count": 1}
                },
            },
        )
        # Should show "1 / 3" (1 accepted out of 3 total)
        assert b"1 / 3" in response.content

    def test_shows_stats_per_category(self, panel_client, active_user, event):
        # Create two categories with different stats
        category1 = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        category2 = ProposalCategory.objects.create(
            event=event, name="Workshops", slug="workshops"
        )
        # Category1: 2 sessions, 1 accepted
        Session.objects.create(
            event=event,
            category=category1,
            presenter=active_user,
            title="RPG 1",
            slug="rpg-1",
            participants_limit=5,
            status="pending",
        )
        Session.objects.create(
            event=event,
            category=category1,
            presenter=active_user,
            title="RPG Accepted",
            slug="rpg-accepted",
            participants_limit=5,
            status="accepted",
        )
        # Category2: 1 session, 0 accepted
        Session.objects.create(
            event=event,
            category=category2,
            presenter=active_user,
            title="Workshop 1",
            slug="workshop-1",
            participants_limit=5,
            status="pending",
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp.html",
            context_data={
                **panel_context(
                    event,
                    active_nav="cfp",
                    hosts_count=1,
                    pending_proposals=1 + 1,
                    total_proposals=1 + 1 + 1,
                    total_sessions=1 + 1,
                ),
                "active_tab": "types",
                "tab_urls": cfp_tab_urls(event),
                "categories": [
                    ProposalCategoryDTO(
                        pk=category1.pk,
                        name="RPG",
                        slug="rpg",
                        description="",
                        start_time=None,
                        end_time=None,
                        min_participants_limit=0,
                        max_participants_limit=0,
                        durations=[],
                    ),
                    ProposalCategoryDTO(
                        pk=category2.pk,
                        name="Workshops",
                        slug="workshops",
                        description="",
                        start_time=None,
                        end_time=None,
                        min_participants_limit=0,
                        max_participants_limit=0,
                        durations=[],
                    ),
                ],
                "category_stats": {
                    category1.pk: {"proposals_count": 1 + 1, "accepted_count": 1},
                    category2.pk: {"proposals_count": 1, "accepted_count": 0},
                },
            },
        )
        # Should show "1 / 2" for RPG and "0 / 1" for Workshops
        assert b"1 / 2" in response.content
        assert b"0 / 1" in response.content
