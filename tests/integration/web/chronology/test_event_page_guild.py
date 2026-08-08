"""The presenter's guild mark riding along on their programme cards."""

from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.adapters.web.django.views import COMPACT_SCHEDULE_MIN_SESSIONS
from ludamus.links.db.django.models import Guild, GuildMembership
from ludamus.pacts.guild import GuildMarkDTO
from tests.integration.conftest import (
    PNG_BYTES,
    AgendaItemFactory,
    SessionFactory,
    SphereFactory,
)
from tests.integration.utils import assert_response


class EventPageMarks:
    """Matches the event page context by the guild marks on its cards.

    test_event_page.py asserts the rest of that context exhaustively, so these
    tests look at the marks alone — plus the card count and the schedule mode,
    which say the marks were read off the page these tests meant to render.
    """

    def __init__(
        self, marks: list[GuildMarkDTO], *, cards: int = 1, compact: bool = False
    ) -> None:
        self.marks = marks
        self.cards = cards
        self.compact = compact

    def _found(self, context: dict) -> list[GuildMarkDTO]:
        return [
            card.guild
            for hour in context.get("hour_data", {}).values()
            for card in hour
            if card.guild
        ]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, dict):
            return NotImplemented
        drawn = sum(len(hour) for hour in other.get("hour_data", {}).values())
        return (
            drawn == self.cards
            and self._found(other) == self.marks
            and other.get("compact_schedule") is self.compact
        )

    def __hash__(self) -> int:
        return hash((tuple(self.marks), self.cards, self.compact))

    def __repr__(self) -> str:
        return (
            f"EventPageMarks({self.marks!r}, cards={self.cards},"
            f" compact={self.compact})"
        )


def _url(event):
    return reverse("web:chronology:event", kwargs={"slug": event.slug})


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
            context_data=EventPageMarks(
                [GuildMarkDTO(pk=guild.pk, name="Topory", logo_url="")]
            ),
            template_name=["chronology/event.html"],
        )

    def test_card_renders_the_mark_when_the_guild_has_a_logo(
        self, client, event, agenda_item, active_user, sphere, guild
    ):
        session = agenda_item.session
        session.presenter = active_user
        session.save()
        guild.logo.save("mark.png", SimpleUploadedFile("mark.png", PNG_BYTES))
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=active_user)

        response = client.get(_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=EventPageMarks(
                [GuildMarkDTO(pk=guild.pk, name="Topory", logo_url=guild.logo.url)]
            ),
            template_name=["chronology/event.html"],
        )

    def test_card_has_no_guild_when_the_presenter_is_in_none(
        self, client, event, agenda_item, active_user, guild
    ):
        session = agenda_item.session
        session.presenter = active_user
        session.save()

        response = client.get(_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=EventPageMarks([]),
            template_name=["chronology/event.html"],
        )

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

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=EventPageMarks([]),
            template_name=["chronology/event.html"],
        )

    def test_a_presenter_less_session_is_left_alone(self, client, event, agenda_item):
        session = agenda_item.session
        session.presenter = None
        session.display_name = "Someone Offline"
        session.save()

        response = client.get(_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=EventPageMarks([]),
            template_name=["chronology/event.html"],
        )


class TestGuildMarkOnTheCompactSchedule:
    """At COMPACT_SCHEDULE_MIN_SESSIONS the page swaps to the compact rows.

    That is the shape a real convention renders in, so the mark has to survive
    the switch — the card grid is the small-event case, not the common one.
    """

    def test_compact_rows_carry_the_guild(
        self, client, event, agenda_item, active_user, sphere, guild, space
    ):
        session = agenda_item.session
        session.presenter = active_user
        session.save()
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=active_user)
        for index in range(COMPACT_SCHEDULE_MIN_SESSIONS):
            extra = SessionFactory(event=event, slug=f"filler-{index}")
            AgendaItemFactory(
                session=extra,
                space=space,
                start_time=agenda_item.start_time,
                end_time=agenda_item.end_time,
            )

        response = client.get(_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=EventPageMarks(
                [GuildMarkDTO(pk=guild.pk, name="Topory", logo_url="")],
                cards=COMPACT_SCHEDULE_MIN_SESSIONS + 1,
                compact=True,
            ),
            template_name=["chronology/event.html"],
        )
