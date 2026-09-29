from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import SphereSubscription
from ludamus.pacts.dashboard import DashboardDTO, DashboardRole
from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.multiverse import SphereVisibility
from tests.integration.conftest import (
    AgendaItemFactory,
    EncounterFactory,
    EncounterRSVPFactory,
    EventFactory,
    SessionFactory,
    SessionParticipationFactory,
    SpaceFactory,
)
from tests.integration.utils import assert_response, assert_response_404

DASHBOARD_URL = reverse("web:dashboard")


def _titles(cards):
    return [card.title for card in cards]


class TestDashboardPageView:
    def test_anonymous_visitors_are_sent_to_log_in(self, client):
        response = client.get(DASHBOARD_URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/crowd/login-required/?next={DASHBOARD_URL}",
        )

    def test_a_sphere_domain_has_no_dashboard_of_its_own(
        self, authenticated_client, non_root_sphere
    ):
        # The dashboard reads across every sphere, so it belongs to the root
        # one; a sphere's members have its feed instead.
        response = authenticated_client.get(
            DASHBOARD_URL, HTTP_HOST=non_root_sphere.site.domain
        )

        assert_response_404(response)

    def test_an_empty_account_still_gets_a_page(self, authenticated_client):
        response = authenticated_client.get(DASHBOARD_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "dashboard": DashboardDTO(
                    agenda=[], open_encounters=[], sphere_feed=[], discover=[]
                ),
                "can_create_encounter": True,
            },
            template_name="dashboard/index.html",
        )

    def test_agenda_gathers_seats_and_encounters_across_spheres(
        self, authenticated_client, active_user, non_root_sphere, sphere
    ):
        event = EventFactory(sphere=non_root_sphere)
        session = SessionFactory(event=event, title="Kill Your Necromancer")
        AgendaItemFactory(
            session=session,
            space=SpaceFactory(event=event),
            start_time=datetime.now(UTC) + timedelta(days=3),
        )
        SessionParticipationFactory(
            session=session, user=active_user, status="confirmed"
        )
        mine = EncounterFactory(
            sphere=sphere, creator=active_user, title="Brass: Birmingham"
        )
        joined = EncounterFactory(sphere=sphere, title="Root")
        EncounterRSVPFactory(encounter=joined, user=active_user)

        response = authenticated_client.get(DASHBOARD_URL)

        dashboard = response.context_data["dashboard"]
        assert set(_titles(dashboard.agenda)) == {
            "Kill Your Necromancer",
            mine.title,
            joined.title,
        }
        roles = {card.title: card.role for card in dashboard.agenda}
        assert roles[mine.title] == DashboardRole.ORGANIZING
        assert roles[joined.title] == DashboardRole.SIGNED_UP
        # Cross-sphere rows have to carry their own host.
        session_card = next(
            card for card in dashboard.agenda if card.title == "Kill Your Necromancer"
        )
        assert session_card.url.startswith(f"https://{non_root_sphere.site.domain}/")

    def test_for_you_skips_what_this_member_already_holds(
        self, authenticated_client, active_user, sphere
    ):
        open_one = EncounterFactory(sphere=sphere, is_public=True, title="Open table")
        already_mine = EncounterFactory(
            sphere=sphere, is_public=True, creator=active_user
        )
        rsvpd = EncounterFactory(sphere=sphere, is_public=True)
        EncounterRSVPFactory(encounter=rsvpd, user=active_user)

        response = authenticated_client.get(DASHBOARD_URL)

        dashboard = response.context_data["dashboard"]
        assert _titles(dashboard.open_encounters) == [open_one.title]
        assert already_mine.title not in _titles(dashboard.open_encounters)

    def test_discover_offers_other_spheres_and_says_which_you_follow(
        self, authenticated_client, active_user, non_root_sphere
    ):
        EventFactory(sphere=non_root_sphere)

        response = authenticated_client.get(DASHBOARD_URL)
        [suggestion] = response.context_data["dashboard"].discover
        assert suggestion.pk == non_root_sphere.pk
        assert suggestion.upcoming_count == 1
        assert suggestion.is_subscribed is False

        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        response = authenticated_client.get(DASHBOARD_URL)
        [suggestion] = response.context_data["dashboard"].discover
        assert suggestion.is_subscribed is True

    def test_a_private_sphere_stays_off_a_stranger_s_dashboard(
        self, authenticated_client, active_user, non_root_sphere
    ):
        non_root_sphere.visibility = SphereVisibility.PRIVATE
        non_root_sphere.encounters_policy = EncountersPolicy.EVERYONE
        non_root_sphere.save()
        # A subscription from before the sphere went private is no key to it.
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        EventFactory(sphere=non_root_sphere)
        EncounterFactory(sphere=non_root_sphere, is_public=True)

        response = authenticated_client.get(DASHBOARD_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "dashboard": DashboardDTO(
                    agenda=[], open_encounters=[], sphere_feed=[], discover=[]
                ),
                "can_create_encounter": True,
            },
            template_name="dashboard/index.html",
        )

    def test_a_private_sphere_s_manager_still_gets_its_feed(
        self, authenticated_client, active_user, non_root_sphere
    ):
        non_root_sphere.visibility = SphereVisibility.PRIVATE
        non_root_sphere.save()
        non_root_sphere.managers.add(active_user)
        event = EventFactory(sphere=non_root_sphere)

        response = authenticated_client.get(DASHBOARD_URL)

        assert _titles(response.context_data["dashboard"].sphere_feed) == [event.name]


class TestSphereSubscriptionActions:
    @pytest.fixture(name="subscribe_url")
    def subscribe_url_fixture(self, non_root_sphere):
        return reverse("web:sphere-subscribe", kwargs={"pk": non_root_sphere.pk})

    def test_subscribe_then_unsubscribe(
        self, authenticated_client, active_user, non_root_sphere, subscribe_url
    ):
        response = authenticated_client.post(subscribe_url)

        assert_response(response, HTTPStatus.FOUND, url=DASHBOARD_URL)
        assert SphereSubscription.objects.filter(
            sphere=non_root_sphere, user=active_user
        ).exists()

        response = authenticated_client.post(
            reverse("web:sphere-unsubscribe", kwargs={"pk": non_root_sphere.pk})
        )

        assert_response(response, HTTPStatus.FOUND, url=DASHBOARD_URL)
        assert not SphereSubscription.objects.filter(
            sphere=non_root_sphere, user=active_user
        ).exists()

    def test_subscribing_twice_is_harmless(
        self, authenticated_client, active_user, non_root_sphere, subscribe_url
    ):
        authenticated_client.post(subscribe_url)
        authenticated_client.post(subscribe_url)

        assert (
            SphereSubscription.objects.filter(
                sphere=non_root_sphere, user=active_user
            ).count()
            == 1
        )

    def test_a_sphere_id_that_names_nothing_is_a_404(self, authenticated_client):
        response = authenticated_client.post(
            reverse("web:sphere-subscribe", kwargs={"pk": 10_000})
        )

        assert_response_404(response)
        assert not SphereSubscription.objects.exists()

    def test_the_root_sphere_is_nobody_s_subscription(
        self, authenticated_client, sphere
    ):
        # Everyone signed in is already on it; offering to follow it would be
        # a control with nothing behind it.
        response = authenticated_client.post(
            reverse("web:sphere-subscribe", kwargs={"pk": sphere.pk})
        )

        assert_response_404(response)
        assert not SphereSubscription.objects.exists()

    def test_a_private_sphere_is_a_404(self, authenticated_client, non_root_sphere):
        non_root_sphere.visibility = SphereVisibility.PRIVATE
        non_root_sphere.save()

        response = authenticated_client.post(
            reverse("web:sphere-subscribe", kwargs={"pk": non_root_sphere.pk})
        )

        assert_response_404(response)
        assert not SphereSubscription.objects.exists()
