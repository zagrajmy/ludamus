# The guild mark yields the avatar's bottom-right corner to the shadowban
# warning badge. Which corner it takes is components/guild_notch.html's job;
# what these tests pin is the flag that drives it, which is where a wrong user
# id or a reversed ban direction would show up.
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import Guild, GuildMembership
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response


def _event_url(event):
    return reverse("web:chronology:event", kwargs={"slug": event.slug})


def _modal_url(event, session_id):
    return reverse(
        "web:chronology:session-modal",
        kwargs={"event_slug": event.slug, "session_id": session_id},
    )


# Matches the modal context by the presenter-warning flag alone;
# test_session_modal.py asserts that context exhaustively.
class ModalPresenterFlag:
    def __init__(self, *, flagged: bool) -> None:
        self.flagged = flagged

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, dict):
            return NotImplemented
        data = other.get("data")
        return getattr(data, "presenter_is_shadowbanned", None) is self.flagged

    def __hash__(self) -> int:
        return hash(self.flagged)

    def __repr__(self) -> str:
        return f"ModalPresenterFlag({self.flagged!r})"


# Matches the event page context by each card's presenter-warning flag, in
# order. test_event_page.py asserts that context exhaustively. Comparing the
# whole list also means a page that rendered no cards cannot pass.
class PresenterFlags:
    def __init__(self, flags: list[bool]) -> None:
        self.flags = flags

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, dict):
            return NotImplemented
        cards = [card for hour in other.get("hour_data", {}).values() for card in hour]
        return [card.presenter_is_shadowbanned for card in cards] == self.flags

    def __hash__(self) -> int:
        return hash(tuple(self.flags))

    def __repr__(self) -> str:
        return f"PresenterFlags({self.flags!r})"


@pytest.fixture(name="guild")
def guild_fixture(sphere):
    return Guild.objects.create(sphere=sphere, name="Topory", slug="topory")


@pytest.fixture(name="presenter")
def presenter_fixture(agenda_item, sphere, guild):
    presenter = UserFactory(
        username="auth0|gm", email="gm@example.com", name="Grzegorz"
    )
    session = agenda_item.session
    session.presenter = presenter
    session.save()
    GuildMembership.objects.create(sphere=sphere, guild=guild, member=presenter)
    return presenter


class TestEventPage:
    def test_card_flags_a_presenter_the_viewer_shadowbanned(
        self, authenticated_client, active_user, event, presenter
    ):
        active_user.shadowbanned.add(presenter)

        response = authenticated_client.get(_event_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=PresenterFlags([True]),
            template_name=["chronology/event.html"],
        )

    def test_card_is_unflagged_without_a_shadowban(
        self, authenticated_client, event, presenter
    ):
        response = authenticated_client.get(_event_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=PresenterFlags([False]),
            template_name=["chronology/event.html"],
        )

    def test_a_ban_in_the_other_direction_does_not_flag_the_presenter(
        self, authenticated_client, active_user, event, presenter
    ):
        # The presenter banning the viewer is the pretend-full case, a different
        # affordance entirely. It must not light up the viewer's own warning.
        presenter.shadowbanned.add(active_user)

        response = authenticated_client.get(_event_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=PresenterFlags([False]),
            template_name=["chronology/event.html"],
        )

    def test_an_anonymous_viewer_has_nobody_shadowbanned(
        self, client, event, presenter
    ):
        response = client.get(_event_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=PresenterFlags([False]),
            template_name=["chronology/event.html"],
        )

    def test_a_presenter_less_session_is_never_flagged(
        self, authenticated_client, event, agenda_item
    ):
        # The stand-in UserInfo carries pk 0, which must not collide with a real
        # shadowban target.
        session = agenda_item.session
        session.presenter = None
        session.display_name = "Someone Offline"
        session.save()

        response = authenticated_client.get(_event_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=PresenterFlags([False]),
            template_name=["chronology/event.html"],
        )


class TestSessionModal:
    def test_modal_flags_a_presenter_the_viewer_shadowbanned(
        self, authenticated_client, active_user, event, agenda_item, presenter
    ):
        active_user.shadowbanned.add(presenter)

        response = authenticated_client.get(_modal_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=ModalPresenterFlag(flagged=True),
            template_name="chronology/parts/session-modal.html",
        )

    def test_modal_is_unflagged_without_a_shadowban(
        self, authenticated_client, event, agenda_item, presenter
    ):
        response = authenticated_client.get(_modal_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=ModalPresenterFlag(flagged=False),
            template_name="chronology/parts/session-modal.html",
        )
