from dataclasses import replace
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.template import Context, Template
from django.utils import timezone, translation

from ludamus.gates.web.django.templatetags.cfp_tags import space_sort_path_json
from tests.integration.conftest import AgendaItemFactory, SessionFactory
from tests.integration.web.chronology.helpers import proposal_card, session_card


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _tags(html):
    parser = _Tags()
    parser.feed(html)
    return parser.tags


def _attrs(fragment):
    return _tags(f"<div {fragment}></div>")[0][1]


def _render(source, **context):
    return Template("{% load schedule_tags %}" + source).render(Context(context))


def _text(html):
    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    parser = Text()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


@pytest.fixture(name="card")
def scheduled_card(event, space, active_user):
    session = SessionFactory(
        event=event,
        presenter=active_user,
        facilitator_name="Ada Lovelace",
        title="Difference Engines",
        participants_limit=10,
        min_age=16,
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
        attrs = _attrs(_render("{% session_data_attrs data %}", data=card))

        local_start = timezone.localtime(card.agenda_item.start_time)
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
            "data-session-end": (
                timezone.localtime(card.agenda_item.end_time).isoformat()
            ),
            "data-start": local_start.isoformat(),
            "data-end": timezone.localtime(card.agenda_item.end_time).isoformat(),
            "data-day": local_start.strftime("%Y-%m-%d"),
            "data-day-label": (
                local_start.strftime("%A, ") + f"{local_start.day} {local_start:%B}"
            ),
            "data-hour": local_start.strftime("%H:%M"),
        }

    def test_ledger_row_is_clipped_to_its_occurrence_and_marks_the_ended(self, card):
        ended = replace(card, is_ended=True, is_ongoing=True)
        start = timezone.localtime(card.agenda_item.start_time)
        end = start + timedelta(minutes=30)

        attrs = _attrs(
            _render(
                "{% session_data_attrs data start end %}",
                data=ended,
                start=start,
                end=end,
            )
        )

        assert attrs["data-ended"] is None
        assert attrs["data-status"] == "ended"
        assert attrs["data-start"] == start.isoformat()
        assert attrs["data-end"] == end.isoformat()
        assert (
            attrs["data-session-end"]
            == timezone.localtime(card.agenda_item.end_time).isoformat()
        )

    def test_started_session_reads_in_progress_until_it_ends(self, card):
        attrs = _attrs(
            _render(
                "{% session_data_attrs data %}", data=replace(card, is_ongoing=True)
            )
        )

        assert attrs["data-status"] == "in-progress"
        assert "data-ended" not in attrs

    def test_proposal_carries_no_time(self, event, active_user):
        session = SessionFactory(event=event, presenter=active_user, min_age=0)
        data = proposal_card(session, presenter=active_user)

        attrs = _attrs(_render("{% session_data_attrs data %}", data=data))

        assert attrs["data-status"] == "proposal"
        assert attrs["data-takes-enrollment"] == "false"
        assert not attrs["data-space"]
        assert "data-start" not in attrs
        assert "data-session-end" not in attrs


class TestSessionAvailability:
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
            rendered = _render(
                "{% session_availability data %}", data=replace(card, **overrides)
            )

        assert _text(rendered) == expected

    def test_no_enrollment_renders_nothing(self, card):
        data = replace(
            card, session=card.session.model_copy(update={"participants_limit": 0})
        )

        assert not _render("{% session_availability data %}", data=data)

    def test_scarce_seats_take_the_warning_tone(self, card):
        rendered = _render(
            "{% session_availability data %}",
            data=replace(card, is_enrollment_available=True, enrolled_count=9),
        )

        assert "text-coral-600" in rendered


class TestBookmarkToggle:
    def test_signed_in_viewer_gets_a_toggle(self, card, active_user):
        rendered = _render(
            '{% bookmark_toggle data wrapper_class="shrink-0" %}',
            data=replace(card, user_bookmarked=True, bookmark_count=3),
            current_user=active_user,
        )

        tags = dict(_tags(rendered))
        button = tags["button"]
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
        assert _text(rendered) == "Bookmark session 3"

    def test_anonymous_viewer_sees_the_count(self, card):
        with translation.override("en"):
            rendered = _render(
                "{% bookmark_toggle data %}", data=replace(card, bookmark_count=2)
            )

        assert "data-bookmark-toggle" not in rendered
        assert _text(rendered) == "2 Bookmarked by 2 people"

    def test_quiet_session_renders_nothing_for_an_anonymous_viewer(self, card):
        assert not _render("{% bookmark_toggle data %}", data=card)
