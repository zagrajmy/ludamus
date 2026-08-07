"""The presenter's guild mark riding along on their programme cards.

The surrounding page context is asserted exhaustively in test_event_page.py;
these tests are about the guild field alone, so they match the rest of the
context with ANY rather than restating it.
"""

from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import Guild, GuildMembership
from ludamus.pacts.guild import GuildMarkDTO
from tests.integration.conftest import SphereFactory
from tests.integration.utils import assert_response


def _url(event):
    return reverse("web:chronology:event", kwargs={"slug": event.slug})


def _cards(response):
    return [
        card for cards in response.context_data["hour_data"].values() for card in cards
    ]


@pytest.fixture(name="guild")
def guild_fixture(sphere):
    return Guild.objects.create(sphere=sphere, name="Topory", slug="topory")


class TestGuildMarkOnCards:
    def test_card_carries_the_presenters_guild(
        self, client, event, agenda_item, active_user, sphere, guild
    ):
        session = agenda_item.session
        session.presenter = active_user
        session.save()
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=active_user)

        response = client.get(_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=ANY,
            template_name=["chronology/event.html"],
        )
        assert [card.guild for card in _cards(response)] == [
            GuildMarkDTO(pk=guild.pk, name="Topory", logo_url="")
        ]

    def test_card_has_no_guild_when_the_presenter_is_in_none(
        self, client, event, agenda_item, active_user, guild
    ):
        session = agenda_item.session
        session.presenter = active_user
        session.save()

        response = client.get(_url(event))

        assert [card.guild for card in _cards(response)] == [None]

    def test_a_membership_in_another_sphere_does_not_leak(
        self, client, event, agenda_item, active_user
    ):
        session = agenda_item.session
        session.presenter = active_user
        session.save()
        other_sphere = SphereFactory()
        foreign = Guild.objects.create(
            sphere=other_sphere, name="Elsewhere", slug="elsewhere"
        )
        GuildMembership.objects.create(
            sphere=other_sphere, guild=foreign, member=active_user
        )

        response = client.get(_url(event))

        assert [card.guild for card in _cards(response)] == [None]

    def test_a_presenter_less_session_is_left_alone(self, client, event, agenda_item):
        session = agenda_item.session
        session.presenter = None
        session.display_name = "Someone Offline"
        session.save()

        response = client.get(_url(event))

        assert [card.guild for card in _cards(response)] == [None]
