from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse
from zeal import zeal_ignore

from ludamus.gates.web.django.chronology.enrollment_presentation import (
    SessionUserParticipationData,
)
from ludamus.links.db.django.models import SessionParticipation
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.chronology.test_session_enroll_page import _party_context


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _enroll_url(session_id: int, event_slug: str) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )


def _is_deniably_full(card):
    # A pretend-full card has to be indistinguishable from a real full one: no
    # spot left, and every seat taken by a simulacrum (negative pk).
    return (
        card.is_full
        and card.spots_left == 0
        and card.enrolled_count == card.effective_participants_limit
        and all(seat.user.pk < 0 for seat in card.session_participations)
    )


# Matches a chronology context by how its cards are masked — the event page's
# `sessions` and `hour_data`, or the session modal's `data`. test_event_page.py
# and test_session_modal.py assert those contexts exhaustively.
class MaskedCards:
    def __init__(self, *, pretend_full: list[bool]) -> None:
        self.pretend_full = pretend_full

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, dict):
            return NotImplemented
        if "data" in other:
            cards = [other["data"]]
        else:
            cards = list(other.get("sessions", []))
            hour_cards = [
                card for hour in other.get("hour_data", {}).values() for card in hour
            ]
            if [card.pretend_full for card in hour_cards] != self.pretend_full:
                return False
        return [card.pretend_full for card in cards] == self.pretend_full and all(
            _is_deniably_full(card) for card in cards if card.pretend_full
        )

    def __hash__(self) -> int:
        return hash(tuple(self.pretend_full))

    def __repr__(self) -> str:
        return f"MaskedCards(pretend_full={self.pretend_full!r})"


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

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=MaskedCards(pretend_full=[True]),
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
            context_data=MaskedCards(pretend_full=[True]),
            template_name="chronology/parts/session-modal.html",
            contains="Session full",
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

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=MaskedCards(pretend_full=[False]),
            template_name=["chronology/event.html"],
            contains="Visible Game",
        )
        (card,) = response.context["sessions"]
        assert not card.is_full

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_page_renders_standard_full_state(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm2")

        response = authenticated_client.get(_enroll_url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                **_party_context(active_user),
                "companions": [],
                "event": agenda_item.space.event,
                "form": ANY,
                "session": session,
                "shadowban_warnings": [],
                "user_data": [
                    SessionUserParticipationData(
                        user=UserDTO.model_validate(active_user),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    )
                ],
            },
            template_name="chronology/enroll_select.html",
        )
        page_session = response.context["session"]
        assert page_session.is_full
        # effective_participants_limit walks event.enrollment_configs; the
        # context instance has no prefetch, so exempt this assertion-side read
        # from zeal instead of flagging the view under test.
        with zeal_ignore():
            limit = page_session.effective_participants_limit
        assert page_session.enrolled_count == limit
        assert page_session.waiting_count == 0

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
