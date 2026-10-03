from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    SessionBookmark,
    SphereSubscription,
)
from ludamus.pacts.dashboard import DASHBOARD_PAST_EVENTS, DashboardDTO, DashboardRole
from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.legacy import SessionParticipationStatus
from ludamus.pacts.multiverse import SphereVisibility
from tests.integration.conftest import (
    AgendaItemFactory,
    EncounterFactory,
    EncounterRSVPFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SessionParticipationFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404

DASHBOARD_URL = reverse("web:dashboard")
EMPTY_DASHBOARD = DashboardDTO(
    agenda=[], open_encounters=[], sphere_feed=[], discover=[], past_events=[]
)


def _titles(cards):
    return [card.title for card in cards]


def _bookmarked_session(event, *, user, title="Mörk Borg", days_ahead=1):
    session = SessionFactory(
        event=event,
        title=title,
        participants_limit=4,
        category=ProposalCategoryFactory(event=event),
    )
    AgendaItemFactory(
        session=session,
        space=SpaceFactory(event=event),
        start_time=datetime.now(UTC) + timedelta(days=days_ahead),
    )
    SessionBookmark.objects.create(user=user, session=session)
    return session


def _past_event(sphere, *, name="Kapitularz 2025", days_ago=30):
    start = datetime.now(UTC) - timedelta(days=days_ago)
    return EventFactory(
        sphere=sphere, name=name, start_time=start, end_time=start + timedelta(days=2)
    )


def _scheduled_session(event, *, presenter=None):
    session = SessionFactory(
        event=event,
        presenter=presenter or UserFactory(),
        category=ProposalCategoryFactory(event=event),
    )
    AgendaItemFactory(
        session=session,
        space=SpaceFactory(event=event),
        start_time=event.start_time + timedelta(hours=2),
    )
    return session


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
            context_data={"dashboard": EMPTY_DASHBOARD, "can_create_encounter": True},
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

    def test_agenda_gathers_starred_sessions_across_events(
        self, authenticated_client, active_user, non_root_sphere, sphere
    ):
        abroad = EventFactory(sphere=non_root_sphere)
        at_home = EventFactory(sphere=sphere)
        later = _bookmarked_session(
            abroad, user=active_user, title="Mothership", days_ahead=3
        )
        SessionParticipationFactory(session=later, status="confirmed")
        # An offered seat is held for its waiter, so it is not free either.
        SessionParticipationFactory(session=later, status="offered")
        _bookmarked_session(at_home, user=active_user, title="Mörk Borg", days_ahead=2)
        held = _bookmarked_session(at_home, user=active_user, title="Held seat")
        SessionParticipationFactory(session=held, user=active_user, status="confirmed")
        _bookmarked_session(
            at_home, user=active_user, title="Already over", days_ahead=-3
        )

        response = authenticated_client.get(DASHBOARD_URL)

        dashboard = response.context_data["dashboard"]
        assert _titles(dashboard.agenda) == ["Held seat", "Mörk Borg", "Mothership"]
        roles = {card.title: card.role for card in dashboard.agenda}
        # A starred seat you also hold is one row, and it says you hold it.
        assert roles["Held seat"] == DashboardRole.SIGNED_UP
        assert roles["Mörk Borg"] == DashboardRole.BOOKMARKED
        mothership = dashboard.agenda[2]
        assert mothership.role == DashboardRole.BOOKMARKED
        assert (mothership.attending_count, mothership.capacity) == (2, 4)
        assert mothership.url.startswith(f"https://{non_root_sphere.site.domain}/")

    def test_another_member_s_bookmarks_stay_theirs(self, authenticated_client, sphere):
        _bookmarked_session(EventFactory(sphere=sphere), user=UserFactory())

        response = authenticated_client.get(DASHBOARD_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"dashboard": EMPTY_DASHBOARD, "can_create_encounter": True},
            template_name="dashboard/index.html",
        )

    def test_a_bookmark_outlives_its_sphere_going_private(
        self, authenticated_client, active_user, non_root_sphere
    ):
        # The member could see the session when they saved it; losing that
        # access later doesn't take their own list away from them.
        _bookmarked_session(EventFactory(sphere=non_root_sphere), user=active_user)
        non_root_sphere.visibility = SphereVisibility.PRIVATE
        non_root_sphere.save()

        response = authenticated_client.get(DASHBOARD_URL)

        dashboard = response.context_data["dashboard"]
        assert _titles(dashboard.agenda) == ["Mörk Borg"]

    def test_a_bookmark_outlives_its_event_being_unpublished(
        self, authenticated_client, active_user, non_root_sphere
    ):
        event = EventFactory(sphere=non_root_sphere)
        _bookmarked_session(event, user=active_user)
        event.publication_time = None
        event.save()

        response = authenticated_client.get(DASHBOARD_URL)

        dashboard = response.context_data["dashboard"]
        assert _titles(dashboard.agenda) == ["Mörk Borg"]

    def test_agenda_says_where_this_member_waits_or_has_a_seat_offered(
        self, authenticated_client, active_user, non_root_sphere
    ):
        event = EventFactory(sphere=non_root_sphere)
        waiting = _bookmarked_session(event, user=active_user, title="Waiting")
        offered = _bookmarked_session(event, user=active_user, title="Offered")
        SessionParticipationFactory(session=waiting, user=active_user, status="waiting")
        deadline = datetime.now(UTC) + timedelta(hours=2)
        SessionParticipationFactory(
            session=offered,
            user=active_user,
            status="offered",
            claim_token="dashboard-token",
            offer_expires_at=deadline,
        )

        response = authenticated_client.get(DASHBOARD_URL)

        dashboard = response.context_data["dashboard"]
        cards = {card.title: card for card in dashboard.agenda}
        assert cards["Waiting"].role == DashboardRole.WAITLISTED
        assert not cards["Waiting"].claim_url
        assert cards["Offered"].role == DashboardRole.OFFERED
        assert cards["Offered"].offer_expires_at == deadline
        assert cards["Offered"].claim_url == reverse(
            "web:dashboard-offer-claim", kwargs={"session_id": offered.pk}
        )
        # Each is one row, and the seat outranks the star.
        assert len(dashboard.agenda) == len(cards)

    def test_a_lapsed_offer_leaves_the_agenda(
        self, authenticated_client, active_user, sphere
    ):
        # Unpublished, so the sphere feed stays out of the picture.
        event = EventFactory(sphere=sphere, publication_time=None)
        SessionParticipationFactory(
            session=_bookmarked_session(event, user=UserFactory()),
            user=active_user,
            status="offered",
            claim_token="lapsed-token",
            offer_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        response = authenticated_client.get(DASHBOARD_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"dashboard": EMPTY_DASHBOARD, "can_create_encounter": True},
            template_name="dashboard/index.html",
        )

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
            context_data={"dashboard": EMPTY_DASHBOARD, "can_create_encounter": True},
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


class TestDashboardPastEvents:
    def test_an_event_you_had_a_seat_at_shows_once_it_is_over(
        self, authenticated_client, active_user, non_root_sphere
    ):
        event = _past_event(non_root_sphere)
        # Two seats at one event are still one event you were at.
        for _ in range(2):
            SessionParticipationFactory(
                session=_scheduled_session(event), user=active_user
            )

        response = authenticated_client.get(DASHBOARD_URL)

        [card] = response.context_data["dashboard"].past_events
        assert card.title == "Kapitularz 2025"
        assert card.origin_name == non_root_sphere.name
        assert card.role == DashboardRole.ATTENDED
        assert card.url.startswith(f"https://{non_root_sphere.site.domain}/")

    def test_a_bookmark_in_an_event_that_is_over_counts_as_being_there(
        self, authenticated_client, active_user, non_root_sphere
    ):
        event = _past_event(non_root_sphere)
        SessionBookmark.objects.create(
            user=active_user, session=_scheduled_session(event)
        )

        response = authenticated_client.get(DASHBOARD_URL)

        dashboard = response.context_data["dashboard"]
        assert _titles(dashboard.past_events) == ["Kapitularz 2025"]
        assert dashboard.agenda == []

    def test_an_event_still_running_is_not_history_yet(
        self, authenticated_client, active_user, non_root_sphere
    ):
        start = datetime.now(UTC) - timedelta(hours=3)
        event = EventFactory(
            sphere=non_root_sphere, start_time=start, end_time=start + timedelta(days=1)
        )
        SessionParticipationFactory(session=_scheduled_session(event), user=active_user)

        response = authenticated_client.get(DASHBOARD_URL)

        assert response.context_data["dashboard"].past_events == []

    def test_a_waitlist_or_a_lapsed_offer_is_not_attendance(
        self, authenticated_client, active_user, non_root_sphere
    ):
        event = _past_event(non_root_sphere)
        SessionParticipationFactory(
            session=_scheduled_session(event), user=active_user, status="waiting"
        )
        SessionParticipationFactory(
            session=_scheduled_session(event),
            user=active_user,
            status="offered",
            claim_token="lapsed-token",
            offer_expires_at=event.start_time,
        )

        response = authenticated_client.get(DASHBOARD_URL)

        assert response.context_data["dashboard"].past_events == []

    def test_running_a_scheduled_session_counts_as_being_there(
        self, authenticated_client, active_user, non_root_sphere
    ):
        presented = _past_event(non_root_sphere, name="Presented", days_ago=10)
        _scheduled_session(presented, presenter=active_user)
        facilitated = _past_event(non_root_sphere, name="Facilitated", days_ago=20)
        session = _scheduled_session(facilitated)
        session.facilitators.add(
            Facilitator.objects.create(
                event=facilitated, user=active_user, display_name="Me", slug="me"
            )
        )
        # A proposal that never made the programme is not a visit.
        rejected = _past_event(non_root_sphere, name="Rejected", days_ago=5)
        SessionFactory(
            event=rejected,
            presenter=active_user,
            category=ProposalCategoryFactory(event=rejected),
            status="rejected",
        )

        response = authenticated_client.get(DASHBOARD_URL)

        assert _titles(response.context_data["dashboard"].past_events) == [
            "Presented",
            "Facilitated",
        ]

    def test_a_removed_session_leaves_no_trace(
        self, authenticated_client, active_user, non_root_sphere
    ):
        session = _scheduled_session(_past_event(non_root_sphere))
        SessionParticipationFactory(session=session, user=active_user)
        session.soft_delete()

        response = authenticated_client.get(DASHBOARD_URL)

        assert response.context_data["dashboard"].past_events == []

    def test_another_member_s_history_stays_theirs(
        self, authenticated_client, non_root_sphere
    ):
        event = _past_event(non_root_sphere)
        SessionParticipationFactory(session=_scheduled_session(event))
        _scheduled_session(event)

        response = authenticated_client.get(DASHBOARD_URL)

        assert response.context_data["dashboard"].past_events == []

    def test_most_recent_first_and_capped(
        self, authenticated_client, active_user, non_root_sphere
    ):
        for weeks_ago in range(DASHBOARD_PAST_EVENTS + 1, 0, -1):
            event = _past_event(
                non_root_sphere, name=f"{weeks_ago} weeks ago", days_ago=weeks_ago * 7
            )
            SessionParticipationFactory(
                session=_scheduled_session(event), user=active_user
            )

        response = authenticated_client.get(DASHBOARD_URL)

        past = _titles(response.context_data["dashboard"].past_events)
        assert past == [f"{n} weeks ago" for n in range(1, DASHBOARD_PAST_EVENTS + 1)]


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


class TestOfferClaimAction:
    @pytest.fixture(name="offer")
    def offer_fixture(self, active_user, non_root_sphere):
        return SessionParticipationFactory(
            session=_bookmarked_session(
                EventFactory(sphere=non_root_sphere), user=active_user
            ),
            user=active_user,
            status="offered",
            claim_token="dashboard-token",
            offer_expires_at=datetime.now(UTC) + timedelta(hours=2),
        )

    @staticmethod
    def _claim_url(session_id):
        return reverse("web:dashboard-offer-claim", kwargs={"session_id": session_id})

    def test_claiming_confirms_the_seat_and_returns_to_the_dashboard(
        self, authenticated_client, offer
    ):
        response = authenticated_client.post(self._claim_url(offer.session_id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=DASHBOARD_URL,
            messages=[
                (
                    messages.SUCCESS,
                    "Spot claimed — you are now confirmed for this session.",
                )
            ],
        )
        offer.refresh_from_db()
        assert offer.status == SessionParticipationStatus.CONFIRMED

    def test_an_expired_offer_says_so_and_changes_nothing(
        self, authenticated_client, offer
    ):
        offer.offer_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        offer.save()

        response = authenticated_client.post(self._claim_url(offer.session_id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=DASHBOARD_URL,
            messages=[
                (messages.ERROR, "This offer has expired or was already claimed.")
            ],
        )
        offer.refresh_from_db()
        assert offer.status == SessionParticipationStatus.OFFERED

    def test_claiming_twice_says_so_instead_of_failing_hard(
        self, authenticated_client, offer
    ):
        authenticated_client.post(self._claim_url(offer.session_id))

        response = authenticated_client.post(self._claim_url(offer.session_id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=DASHBOARD_URL,
            messages=[
                (
                    messages.SUCCESS,
                    "Spot claimed — you are now confirmed for this session.",
                ),
                (messages.ERROR, "This offer has expired or was already claimed."),
            ],
        )
        offer.refresh_from_db()
        assert offer.status == SessionParticipationStatus.CONFIRMED

    def test_one_claim_confirms_the_whole_party(self, authenticated_client, offer):
        # The offer is party-wide, the same as the emailed claim link.
        mate = SessionParticipationFactory(
            session=offer.session,
            status="offered",
            claim_token=offer.claim_token,
            offer_expires_at=offer.offer_expires_at,
        )

        authenticated_client.post(self._claim_url(offer.session_id))

        mate.refresh_from_db()
        assert mate.status == SessionParticipationStatus.CONFIRMED

    def test_someone_else_s_offer_is_left_alone(
        self, authenticated_client, non_root_sphere
    ):
        foreign = SessionParticipationFactory(
            session=_bookmarked_session(
                EventFactory(sphere=non_root_sphere), user=UserFactory()
            ),
            status="offered",
            claim_token="someone-elses-token",
            offer_expires_at=datetime.now(UTC) + timedelta(hours=2),
        )

        response = authenticated_client.post(self._claim_url(foreign.session_id))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=DASHBOARD_URL,
            messages=[
                (messages.ERROR, "This offer has expired or was already claimed.")
            ],
        )
        foreign.refresh_from_db()
        assert foreign.status == SessionParticipationStatus.OFFERED
