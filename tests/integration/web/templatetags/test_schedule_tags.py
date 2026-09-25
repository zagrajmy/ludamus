from dataclasses import replace
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.template import Context, Template
from django.utils import timezone, translation

from ludamus.gates.web.django.chronology.schedule import RoomLaneTile, ScheduleTile
from ludamus.gates.web.django.templatetags.cfp_tags import space_sort_path_json
from ludamus.pacts.durations import format_duration
from ludamus.pacts.guild import GuildMarkDTO
from ludamus.pacts.legacy import LocationData, SessionFieldValueDTO
from tests.integration.conftest import AgendaItemFactory, SessionFactory
from tests.integration.web.chronology.helpers import proposal_card, session_card

_VOID_TAGS = frozenset({"img", "br", "input"})
# What a person could type into any field the row and the tile print: markup
# and the quote that would break out of an attribute.
_PAYLOAD = '<script>alert(1)</script>"'
# The text a row and a tile print from those fields: the link label, the
# title, the host, the room (row only) and the description (row only).
_ROW_TEXT_SLOTS = ("link label", "title", "host", "room", "description")
_TILE_TEXT_SLOTS = ("link label", "title", "host")


class _Markup(HTMLParser):
    # The tags and the text of a fragment: the attribute values are the
    # contract session-filters.ts and session-bookmarks.ts compare exactly,
    # the text is what a reader (or a screen reader) gets.
    def __init__(self):
        super().__init__()
        self.tags = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.parts.append(data)


class _Element(HTMLParser):
    # The text inside the first element whose attributes satisfy `match`.
    def __init__(self, match):
        super().__init__()
        self.match = match
        self.depth = 0
        self.parts = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done or tag in _VOID_TAGS:
            return
        if self.depth:
            self.depth += 1
        elif self.match(dict(attrs)):
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth and tag not in _VOID_TAGS:
            self.depth -= 1
            self.done = not self.depth

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def _squash(parts):
    return " ".join(" ".join(parts).split())


def _tags(html):
    parser = _Markup()
    parser.feed(html)
    return parser.tags


def _text(html):
    parser = _Markup()
    parser.feed(html)
    return _squash(parser.parts)


def _element_text(html, match):
    parser = _Element(match)
    parser.feed(html)
    return _squash(parser.parts)


def _is_bookmark_affordance(attrs):
    return "bookmark-affordance" in (attrs.get("class") or "").split()


def _session_attrs(html):
    return next(
        attrs
        for _tag, attrs in _tags(html)
        if "session" in (attrs.get("class") or "").split()
    )


def _render(source, **context):
    return Template("{% load schedule_tags %}" + source).render(Context(context))


def _row(data, *, start=None, end=None, **context):
    item = data.agenda_item
    tile = ScheduleTile(
        data=data, start=start or item.start_time, end=end or item.end_time
    )
    return _render("{% compact_session_row tile %}", tile=tile, **context)


def _tile(data, *, slot_key="", **context):
    item = data.agenda_item
    tile = RoomLaneTile(
        data=data, start=item.start_time, end=item.end_time, col=3, row_span=2
    )
    return _render(
        "{% room_lane_tile tile slot_key=slot_key %}",
        tile=tile,
        slot_key=slot_key,
        **context,
    )


@pytest.fixture(name="card")
def scheduled_card(event, space, active_user):
    session = SessionFactory(
        event=event,
        presenter=active_user,
        facilitator_name="Ada Lovelace",
        title="Difference Engines",
        description="Babbage's plan, on brass.",
        participants_limit=10,
        min_age=16,
        duration="PT2H",
    )
    start = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(
        days=3
    )
    agenda_item = AgendaItemFactory(
        session=session,
        space=space,
        start_time=start,
        end_time=start + timedelta(hours=2),
    )
    session.refresh_from_db()
    return session_card(agenda_item, presenter=active_user)


class TestSessionDataAttrs:
    def test_card_states_the_session_and_its_room(self, card):
        attrs = _tags(_render("<div {% session_data_attrs data %}></div>", data=card))[
            0
        ][1]

        local_start = timezone.localtime(card.agenda_item.start_time)
        local_end = timezone.localtime(card.agenda_item.end_time)
        assert attrs == {
            "data-title": "difference engines",
            "data-session-id": str(card.session.pk),
            "data-host": "Ada Lovelace",
            "data-tags": "",
            "data-tag-categories": "",
            "data-status": "unavailable",
            "data-takes-enrollment": "true",
            "data-user-enrolled": "false",
            "data-user-waiting": "false",
            "data-bookmarked": "false",
            "data-min-age": "16",
            "data-venue": "",
            "data-venue-name": "",
            "data-space": str(card.loc["space_id"]),
            "data-space-name": card.loc["space_name"],
            "data-space-order": space_sort_path_json(card.loc["sort_path"]),
            "data-session-end": local_end.isoformat(),
            "data-start": local_start.isoformat(),
            "data-end": local_end.isoformat(),
            "data-day": local_start.strftime("%Y-%m-%d"),
            "data-day-label": (
                local_start.strftime("%A, ") + f"{local_start.day} {local_start:%B}"
            ),
            "data-hour": local_start.strftime("%H:%M"),
        }

    def test_proposal_carries_no_time(self, event, active_user):
        session = SessionFactory(event=event, presenter=active_user, min_age=0)
        data = proposal_card(session, presenter=active_user)

        attrs = _tags(_render("<div {% session_data_attrs data %}></div>", data=data))[
            0
        ][1]

        assert attrs["data-status"] == "proposal"
        assert attrs["data-takes-enrollment"] == "false"
        assert not attrs["data-space"]
        assert "data-start" not in attrs
        assert "data-session-end" not in attrs


class TestCompactSessionRow:
    def test_row_is_clipped_to_its_day_and_marks_the_ended(self, card):
        ended = replace(card, is_ended=True, is_ongoing=True)
        start = timezone.localtime(card.agenda_item.start_time)
        end = start + timedelta(minutes=30)

        attrs = _session_attrs(_row(ended, start=start, end=end))

        assert attrs["data-ended"] is None
        assert attrs["data-status"] == "ended"
        assert attrs["data-start"] == start.isoformat()
        assert attrs["data-end"] == end.isoformat()
        assert (
            attrs["data-session-end"]
            == timezone.localtime(card.agenda_item.end_time).isoformat()
        )

    def test_started_session_reads_in_progress_until_it_ends(self, card):
        attrs = _session_attrs(_row(replace(card, is_ongoing=True)))

        assert attrs["data-status"] == "in-progress"
        assert "data-ended" not in attrs

    def test_row_reads_time_title_host_meta_and_description(self, card):
        start = timezone.localtime(card.agenda_item.start_time)
        end = timezone.localtime(card.agenda_item.end_time)
        with translation.override("en"):
            rendered = _row(card)

        assert _text(rendered) == (
            f"Open details for Difference Engines {start:%H:%M} – {end:%H:%M}"
            f" Difference Engines Ada Lovelace {card.loc['space_name']}"
            f" · {format_duration(card.session.duration)} · 16+ · 10 seats"
            " Babbage's plan, on brass."
        )
        link = dict(_tags(rendered))["a"]
        assert link["href"] == f"?session={card.session.pk}"
        assert link["aria-controls"] == f"session-{card.session.pk}"

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        (
            ({}, "10 seats"),
            ({"enrolled_count": 3}, "7 free"),
            ({"is_enrollment_available": True}, "10 spots left"),
            ({"is_enrollment_available": True, "enrolled_count": 9}, "1 spot left"),
            ({"is_enrollment_available": True, "is_full": True}, "Full"),
            (
                {"is_enrollment_available": True, "is_full": True, "waiting_count": 2},
                "Full · 2 waiting",
            ),
            ({"is_ended": True, "is_ongoing": True}, "Ended"),
            ({"is_ongoing": True, "should_show_as_inactive": True}, "In Progress"),
        ),
    )
    def test_label_follows_the_availability_ladder(self, card, overrides, expected):
        with translation.override("en"):
            rendered = _row(replace(card, **overrides))

        meta = _element_text(rendered, lambda attrs: "title" in attrs)
        assert meta.endswith(f" · {expected}")

    def test_no_enrollment_prints_no_label_and_no_separator(self, card):
        data = replace(
            card, session=card.session.model_copy(update={"participants_limit": 0})
        )

        meta = _element_text(_row(data), lambda attrs: "title" in attrs)

        assert meta == (
            f"{card.loc['space_name']} · {format_duration(card.session.duration)}"
            " · 16+"
        )

    def test_scarce_seats_take_the_warning_tone(self, card):
        rendered = _row(replace(card, is_enrollment_available=True, enrolled_count=9))

        assert "text-coral-600" in rendered

    def test_guild_mark_sits_by_the_title(self, card):
        guild = GuildMarkDTO(pk=1, name="Cogwheel", logo_url="https://g.test/c.png")
        with translation.override("en"):
            rendered = _row(replace(card, guild=guild))

        marks = [attrs for tag, attrs in _tags(rendered) if tag == "img"]
        assert [(mark["src"], mark["alt"]) for mark in marks] == [
            ("https://g.test/c.png", "Guild: Cogwheel")
        ]

    def test_guild_without_a_logo_leaves_no_mark(self, card):
        rendered = _row(replace(card, guild=GuildMarkDTO(pk=1, name="Cogwheel")))

        assert "img" not in dict(_tags(rendered))

    def test_signed_in_viewer_gets_a_toggle(self, card, active_user):
        rendered = _row(
            replace(card, user_bookmarked=True, bookmark_count=3),
            current_user=active_user,
        )

        button = dict(_tags(rendered))["button"]
        assert button["aria-pressed"] == "true"
        assert button["data-session-id"] == str(card.session.pk)
        assert "text-coral-600" in button["class"]
        # A bookmarked session shows the solid mark and hides the outline;
        # session-bookmarks.ts swaps the pair on toggle.
        icons = {
            attrs["data-bookmark-icon"]: "hidden" in attrs["class"].split()
            for tag, attrs in _tags(rendered)
            if tag == "svg"
        }
        assert icons == {"outline": True, "solid": False}
        with translation.override("en"):
            rendered = _row(
                replace(card, user_bookmarked=True, bookmark_count=3),
                current_user=active_user,
            )
        assert (
            _element_text(rendered, lambda attrs: "data-bookmark-toggle" in attrs)
            == "Bookmark session 3"
        )

    def test_signed_in_viewer_keeps_a_hidden_zero_to_count_from(
        self, card, active_user
    ):
        rendered = _row(card, current_user=active_user)

        count = next(
            attrs for _tag, attrs in _tags(rendered) if "data-bookmark-count" in attrs
        )
        assert "hidden" in count["class"].split()
        assert (
            _element_text(rendered, lambda attrs: "data-bookmark-count" in attrs) == "0"
        )

    def test_anonymous_viewer_sees_the_count(self, card):
        with translation.override("en"):
            rendered = _row(replace(card, bookmark_count=2))

        assert "data-bookmark-toggle" not in rendered
        badge = _element_text(rendered, _is_bookmark_affordance)
        assert badge == "2 Bookmarked by 2 people"

    def test_quiet_session_carries_no_bookmark_noise(self, card):
        rendered = _row(card)

        assert not [
            attrs for _tag, attrs in _tags(rendered) if _is_bookmark_affordance(attrs)
        ]


@pytest.fixture(name="poisoned")
def poisoned_card(card):
    # _PAYLOAD in every field a person types: the session's words, the host,
    # the room and its venue, a tag, a track, a category and the guild.
    sort_path = ((0, _PAYLOAD, 2), (0, _PAYLOAD, 1))
    return replace(
        card,
        session=card.session.model_copy(
            update={
                "title": _PAYLOAD,
                "description": _PAYLOAD,
                "facilitator_name": _PAYLOAD,
            }
        ),
        presenter=replace(card.presenter, full_name=_PAYLOAD, name=_PAYLOAD),
        loc=LocationData(
            space_id=1,
            parent_id=2,
            space_name=_PAYLOAD,
            parent_name=_PAYLOAD,
            path=f"{_PAYLOAD} > {_PAYLOAD}",
            sort_path=sort_path,
            programme_order=0,
        ),
        field_values=[
            SessionFieldValueDTO(
                field_name="Genre",
                field_question="Genre",
                field_slug="genre",
                field_type="select",
                is_public=True,
                value=[_PAYLOAD],
            )
        ],
        track_names=[_PAYLOAD],
        category_name=_PAYLOAD,
        guild=GuildMarkDTO(pk=1, name=_PAYLOAD, logo_url="https://g.test/c.png"),
        bookmark_count=1,
    )


class TestEscaping:
    # The builders format plain strings and escape by hand, so this pins that
    # every slot a person's words reach was escaped: once (the parsed values
    # read back as typed) and never skipped (no tag survives in the raw HTML).

    @pytest.mark.parametrize("signed_in", (False, True))
    def test_row_escapes_every_typed_field(self, poisoned, active_user, signed_in):
        rendered = _row(poisoned, current_user=active_user if signed_in else None)

        assert "<script" not in rendered
        attrs = _session_attrs(rendered)
        assert attrs["data-title"] == _PAYLOAD
        assert attrs["data-host"] == _PAYLOAD
        assert attrs["data-tags"] == _PAYLOAD
        assert attrs["data-tag-categories"] == (
            f"genre:{_PAYLOAD};__track:{_PAYLOAD};__category:{_PAYLOAD}"
        )
        assert attrs["data-venue-name"] == _PAYLOAD
        assert attrs["data-space-name"] == _PAYLOAD
        assert attrs["data-space-order"] == space_sort_path_json(
            poisoned.loc["sort_path"]
        )
        tags = _tags(rendered)
        meta = next(attrs for tag, attrs in tags if tag == "span" and "title" in attrs)
        assert meta["title"] == f"{_PAYLOAD} > {_PAYLOAD}"
        mark = next(attrs for tag, attrs in tags if tag == "img")
        assert mark["alt"] == f"Guild: {_PAYLOAD}"
        assert _text(rendered).count(_PAYLOAD) == len(_ROW_TEXT_SLOTS)

    @pytest.mark.parametrize("signed_in", (False, True))
    def test_tile_escapes_every_typed_field(self, poisoned, active_user, signed_in):
        rendered = _tile(
            poisoned, slot_key=_PAYLOAD, current_user=active_user if signed_in else None
        )

        assert "<script" not in rendered
        attrs = _session_attrs(rendered)
        assert attrs["data-title"] == _PAYLOAD
        assert attrs["data-host"] == _PAYLOAD
        assert attrs["data-space-name"] == _PAYLOAD
        tags = dict(_tags(rendered))
        assert tags["article"]["data-slot-hour"] == _PAYLOAD
        assert tags["img"]["alt"] == f"Guild: {_PAYLOAD}"
        avatar = next(attrs for _tag, attrs in _tags(rendered) if "role" in attrs)
        assert avatar["aria-label"] == _PAYLOAD
        assert _text(rendered).count(_PAYLOAD) == len(_TILE_TEXT_SLOTS)


class TestRoomLaneTile:
    def test_tile_names_its_slot_and_its_room_column(self, card):
        rendered = _tile(card, slot_key="1700000000")

        tags = dict(_tags(rendered))
        assert tags["article"]["data-slot-hour"] == "1700000000"
        assert tags["a"]["aria-describedby"] == "room-lane-room-3"
        local_start = timezone.localtime(card.agenda_item.start_time)
        assert _session_attrs(rendered)["data-start"] == local_start.isoformat()

    def test_tile_reads_time_and_age(self, card):
        start = timezone.localtime(card.agenda_item.start_time)
        end = timezone.localtime(card.agenda_item.end_time)

        clock = _element_text(
            _tile(card), lambda attrs: attrs.get("data-morph") == "time"
        )

        assert clock == f"{start:%H:%M}–{end:%H:%M} · 16+"

    def test_tile_shows_the_host_with_an_avatar(self, card):
        rendered = _tile(card)

        avatars = [
            attrs for _tag, attrs in _tags(rendered) if attrs.get("role") == "img"
        ]
        assert [avatar["aria-label"] for avatar in avatars] == [
            card.presenter.full_name or card.presenter.name
        ]
        assert (
            _element_text(rendered, lambda attrs: attrs.get("data-morph") == "host")
            == "Ada Lovelace"
        )

    def test_tile_without_a_host_draws_no_presenter_row(self, card):
        data = replace(
            card, session=card.session.model_copy(update={"facilitator_name": ""})
        )

        rendered = _tile(data)

        assert not [attrs for _tag, attrs in _tags(rendered) if "role" in attrs]

    def test_tile_reads_the_availability(self, card):
        with translation.override("en"):
            rendered = _tile(replace(card, is_enrollment_available=True))

        assert (
            _element_text(rendered, lambda attrs: attrs.get("data-morph") == "meta")
            == "10 spots left"
        )
