from http import HTTPStatus

import pytest
from django.urls import reverse
from zeal import zeal_ignore

from ludamus.gates.web.django.event.enroll_presentation import EnrollActions
from ludamus.links.db.django.models import SessionParticipation
from ludamus.pacts import EventDTO
from tests.integration.conftest import UserFactory
from tests.integration.utils import AttributesMatcher, assert_response
from tests.integration.web.chronology.helpers import (
    ENROLLMENT_OPEN,
    enroll_page_context,
    event_page_context,
    masked_card,
    session_card,
)


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _enroll_url(session_id: int, event_slug: str) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )


def _event_page_context(event, card, *, lane, **overrides):
    # The card-layout event page for a signed-in viewer with no enrollments.
    # One scheduled session reaches the template three times: as a card in
    # `sessions`, in `hour_data`, and through the availability lane that
    # `card_days` groups by.
    start_time = card.agenda_item.start_time
    return event_page_context(
        event,
        url=_event_url(event.slug),
        sessions=[card],
        hour_data={start_time: [card]},
        **{lane: {start_time: [card]}},
        **overrides,
    )


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

    @pytest.mark.usefixtures("enrollment_config")
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
        card = masked_card(agenda_item, presenter=session.presenter, seats=10)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_event_page_context(
                event,
                card,
                lane="current_hour_data",
                access=ENROLLMENT_OPEN,
                total_enrolled=10,
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains=["Deniable Game"],
        )
        # The "Session full" affordance renders in the lazy-loaded modal, which
        # applies the same shadowban masking for the banned viewer.
        modal = authenticated_client.get(
            reverse(
                "web:chronology:session-modal",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            )
        )
        assert_response(
            modal,
            HTTPStatus.OK,
            context_data={
                "data": card,
                "event": EventDTO.model_validate(event),
                "event_banned": False,
                "show_roster": True,
                "enroll_opens_at": None,
                "map_pk": None,
                # The deniable card offers what a genuinely full session would.
                "enroll_actions": EnrollActions(
                    submit_value="waitlist",
                    submit_label="Join waiting list",
                    submit_icon="clock",
                    group_label="Enroll with others…",
                ),
            },
            template_name="chronology/parts/session-modal.html",
        )

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

        # No mask for this viewer: the real card, with its real empty roster.
        card = session_card(agenda_item, presenter=session.presenter)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_event_page_context(
                event,
                card,
                lane="future_unavailable_hour_data",
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
            contains="Visible Game",
        )

    def test_masked_modal_keeps_its_footer_when_no_window_is_open(
        self, authenticated_client, agenda_item, active_user, event
    ):
        # The mask is a claim that the session is full, and a footer that
        # vanishes is a tell: a banned viewer could spot the difference by
        # comparing their view with a friend's. See
        # docs/features/crowd/profile/shadowban.md.
        session = _ban_viewer(agenda_item, active_user, username="quiet-gm")

        response = authenticated_client.get(
            reverse(
                "web:chronology:session-modal",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            )
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "data": masked_card(agenda_item, presenter=session.presenter, seats=10),
                "event": EventDTO.model_validate(event),
                "event_banned": False,
                "show_roster": True,
                # The mask claims an open, full session, so it keeps the
                # waiting list a genuinely full one would offer — the viewer's
                # own (empty) set of windows must not shrink the footer.
                "enroll_actions": EnrollActions(
                    submit_value="waitlist",
                    submit_label="Join waiting list",
                    submit_icon="clock",
                    group_label="Enroll with others…",
                ),
                "enroll_opens_at": None,
                "map_pk": None,
            },
            template_name="chronology/parts/session-modal.html",
            contains="Session full",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_page_renders_standard_full_state(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm2")

        response = authenticated_client.get(_enroll_url(session.pk, session.event.slug))

        # The page holds the Session model, which compares by pk — stating the
        # instance would say nothing about the faked counts it renders. The
        # counts walk event.enrollment_configs on an unprefetched instance, so
        # the assertion-side read is exempted from zeal rather than the view
        # under test being flagged for it.
        with zeal_ignore():
            assert_response(
                response,
                HTTPStatus.OK,
                context_data=enroll_page_context(
                    viewer=active_user,
                    agenda_item=agenda_item,
                    session=AttributesMatcher(
                        pk=session.pk, is_full=True, enrolled_count=10, waiting_count=0
                    ),
                ),
                template_name="chronology/enroll_select.html",
            )

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
