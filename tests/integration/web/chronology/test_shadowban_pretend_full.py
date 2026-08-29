from http import HTTPStatus

import pytest
from django.urls import reverse
from zeal import zeal_ignore

from ludamus.gates.web.django.event.enroll_presentation import EnrollActions
from ludamus.links.db.django.models import SessionParticipation
from ludamus.pacts import EventDTO
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.chronology.helpers import (
    CARDS_PER_SESSION,
    assert_card,
    card_buckets,
    enroll_page_context,
    event_page_context,
    every_card,
    is_deniably_full,
)


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _enroll_url(session_id: int, event_slug: str) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )


def _event_page_context(event, buckets, **overrides):
    # The card-layout event page for a signed-in viewer with no enrollments.
    return event_page_context(event, url=_event_url(event.slug), **buckets, **overrides)


def _ban_viewer(agenda_item, viewer, *, username: str):
    banner = UserFactory(username=username, email=f"{username}@example.com", name="GM")
    session = agenda_item.session
    session.presenter = banner
    session.save()
    banner.shadowbanned.add(viewer)
    return session


class TestShadowbanPretendFull:
    # Intended behaviour: the banner's sessions render pretend-full, never
    # hidden — a hidden session would reveal the ban (compare the program
    # with a friend's view), a full one is deniable.
    # See docs/features/crowd/profile/shadowban.md.

    def test_event_page_shows_banner_session_as_full(
        self, authenticated_client, agenda_item, active_user, event
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm")
        session.title = "Deniable Game"
        session.display_name = "Deniable Game"
        session.save()

        response = authenticated_client.get(_event_url(event.slug))

        # The masked card claims an open, fully booked session, so it lands in
        # the current lane and its invented seats count toward the page total.
        buckets = card_buckets(
            response, agenda_item.start_time, lane="current_hour_data"
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_event_page_context(
                event,
                buckets,
                total_enrolled=10,
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains=["Deniable Game"],
        )
        cards = every_card(buckets)
        assert len(cards) == CARDS_PER_SESSION
        assert all(card.pretend_full for card in cards)
        assert all(is_deniably_full(card) for card in cards)
        # The "Session full" affordance renders in the lazy-loaded modal, which
        # applies the same shadowban masking for the banned viewer.
        modal = authenticated_client.get(
            reverse(
                "web:chronology:session-modal",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            )
        )
        modal_card = modal.context_data["data"]
        assert_response(
            modal,
            HTTPStatus.OK,
            context_data={
                "data": modal_card,
                "event": EventDTO.model_validate(event),
                "event_banned": False,
                "show_roster": True,
                # The deniable card offers what a genuinely full session would.
                "enroll_actions": EnrollActions(
                    submit_value="waitlist",
                    submit_label="Join waiting list",
                    submit_icon="clock",
                    group_label="Enroll with others…",
                ),
            },
            template_name="chronology/parts/session-modal.html",
            contains="Session full",
        )
        assert modal_card.pretend_full
        assert is_deniably_full(modal_card)

    def test_event_page_untouched_for_other_users(
        self, authenticated_client, agenda_item, event
    ):
        banned_viewer = UserFactory(
            username="banned-viewer", email="banned-viewer@example.com"
        )
        session = _ban_viewer(agenda_item, banned_viewer, username="other-gm")
        session.title = "Visible Game"
        session.display_name = "Visible Game"
        session.save()

        response = authenticated_client.get(_event_url(event.slug))

        buckets = card_buckets(
            response, agenda_item.start_time, lane="future_unavailable_hour_data"
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_event_page_context(
                event, buckets, has_enrollable_sessions=True, scheduled_count=1
            ),
            template_name=["chronology/event.html"],
            contains="Visible Game",
        )
        cards = every_card(buckets)
        assert len(cards) == CARDS_PER_SESSION
        assert not any(card.pretend_full for card in cards)
        assert not any(card.is_full for card in cards)

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_page_renders_standard_full_state(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm2")

        response = authenticated_client.get(_enroll_url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=enroll_page_context(
                viewer=active_user, agenda_item=agenda_item
            ),
            template_name="chronology/enroll_select.html",
        )
        page_session = response.context_data["session"]
        # effective_participants_limit walks event.enrollment_configs; the
        # context instance has no prefetch, so exempt this assertion-side read
        # from zeal instead of flagging the view under test.
        with zeal_ignore():
            limit = page_session.effective_participants_limit
        assert_card(page_session, is_full=True, enrolled_count=limit, waiting_count=0)

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_post_never_seats_the_shadowbanned(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm3")

        response = authenticated_client.post(
            _enroll_url(session.pk, session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=active_user, session=session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_shadowbanned_companion_not_seated(
        self, authenticated_client, agenda_item, companion
    ):
        # The manager is not banned (so the guard passes), but their companion
        # is — and must not get a seat in the banner's session.
        session = _ban_viewer(agenda_item, companion, username="gm4")

        response = authenticated_client.post(
            _enroll_url(session.pk, session.event.slug),
            data={f"user_{companion.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=companion, session=session
        ).exists()
