from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from ludamus.mills.legacy import (
    PanelService,
    generate_ics_content,
    generate_share_code,
    google_calendar_url,
    outlook_calendar_url,
    render_markdown,
)
from ludamus.pacts import EncounterDTO
from tests.unit.factories import event_dto

START = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
URL = "https://example.test/e/CODE1"
DEFAULT_CODE_LENGTH = 6
LONG_CODE_LENGTH = 12


def _encounter(**overrides):
    fields = {
        "creation_time": START - timedelta(days=7),
        "creator_id": 10,
        "description": "",
        "end_time": None,
        "game": "Gloomhaven",
        "max_participants": 0,
        "pk": 1,
        "place": "",
        "share_code": "CODE1",
        "sphere_id": 3,
        "start_time": START,
        "title": "Game night",
    }
    return EncounterDTO(**{**fields, **overrides})


def _event():
    return event_dto(
        end_time=START + timedelta(days=2),
        name="Con",
        slug="con",
        sphere_id=3,
        start_time=START,
    )


@dataclass
class _Range:
    start_time: datetime
    end_time: datetime


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


class TestShareCode:
    def test_default_length_is_six_base62_chars(self):
        code = generate_share_code()

        assert len(code) == DEFAULT_CODE_LENGTH
        assert code.isalnum()

    def test_length_is_configurable(self):
        assert len(generate_share_code(LONG_CODE_LENGTH)) == LONG_CODE_LENGTH


class TestRenderMarkdown:
    def test_renders_inline_markup_and_line_breaks(self):
        html = render_markdown("**bold**\nnext")

        assert "<strong>bold</strong>" in html
        assert "<br" in html

    def test_keeps_only_the_allowed_tags_and_attributes(self):
        html = render_markdown(
            "<script>alert(1)</script>"
            '<a href="/x" hreflang="en" onclick="y">l</a><u>u</u>'
        )

        assert html.strip() == '<p><a href="/x" rel="noopener noreferrer">l</a>u</p>'


class TestCalendarExports:
    def test_ics_carries_uid_start_and_url_but_no_end_for_open_ended(self):
        lines = generate_ics_content(_encounter(), URL).split("\r\n")

        assert "UID:CODE1@ludamus" in lines
        assert "DTSTART:20260801T180000Z" in lines
        assert "SUMMARY:Game night" in lines
        assert f"URL:{URL}" in lines
        assert not [line for line in lines if line.startswith("DTEND")]
        assert not [line for line in lines if line.startswith("LOCATION")]
        assert not [line for line in lines if line.startswith("DESCRIPTION")]

    def test_ics_prints_end_place_and_description_when_present(self):
        encounter = _encounter(
            end_time=START + timedelta(hours=3), place="Klub", description="Dice"
        )

        lines = generate_ics_content(encounter, URL).split("\r\n")

        assert "DTEND:20260801T210000Z" in lines
        assert "LOCATION:Klub" in lines
        assert "DESCRIPTION:Dice" in lines

    def test_google_link_defaults_open_ended_encounter_to_two_hours(self):
        query = _query(google_calendar_url(_encounter(), URL))

        assert query["dates"] == "20260801T180000Z/20260801T200000Z"

    def test_google_link_keeps_an_explicit_end(self):
        encounter = _encounter(end_time=START + timedelta(hours=3))

        query = _query(google_calendar_url(encounter, URL))

        assert query["dates"] == "20260801T180000Z/20260801T210000Z"

    def test_outlook_link_defaults_open_ended_encounter_to_two_hours(self):
        query = _query(outlook_calendar_url(_encounter(), URL))

        assert query["enddt"] == "2026-08-01T20:00:00+00:00"


class FakeSessionFields:
    def __init__(self, *, used=()):
        self.used = set(used)
        self.rows = {1, 2}

    def has_requirements(self, pk):
        return pk in self.used

    def delete(self, pk):
        self.rows.remove(pk)


class FakeTimeSlots:
    def __init__(self, *, used=()):
        self.used = set(used)
        self.rows = {1, 2}

    def has_proposals(self, pk):
        return pk in self.used

    def delete(self, pk):
        self.rows.remove(pk)


class FakeUow:
    def __init__(self, *, used_fields=(), used_slots=()):
        self.session_fields = FakeSessionFields(used=used_fields)
        self.time_slots = FakeTimeSlots(used=used_slots)


class TestPanelService:
    def test_deletes_an_unused_session_field(self):
        uow = FakeUow()

        assert PanelService(uow).delete_session_field(1)
        assert uow.session_fields.rows == {2}

    def test_keeps_a_session_field_that_a_session_type_requires(self):
        uow = FakeUow(used_fields=[1])

        assert not PanelService(uow).delete_session_field(1)
        assert uow.session_fields.rows == {1, 2}

    def test_deletes_an_unused_time_slot(self):
        uow = FakeUow()

        assert PanelService(uow).delete_time_slot(2)
        assert uow.time_slots.rows == {1}

    def test_keeps_a_time_slot_with_proposals(self):
        uow = FakeUow(used_slots=[2])

        assert not PanelService(uow).delete_time_slot(2)
        assert uow.time_slots.rows == {1, 2}

    def test_a_slot_inside_the_event_with_no_neighbours_is_valid(self):
        errors = PanelService.validate_time_slot(
            START + timedelta(hours=1),
            START + timedelta(hours=2),
            _event(),
            [_Range(START + timedelta(hours=3), START + timedelta(hours=4))],
        )

        assert not errors

    def test_the_first_slot_of_an_event_is_valid(self):
        errors = PanelService.validate_time_slot(
            START, START + timedelta(hours=1), _event(), []
        )

        assert not errors

    def test_a_slot_ending_when_the_event_ends_is_valid(self):
        event = _event()

        errors = PanelService.validate_time_slot(
            event.end_time - timedelta(hours=1), event.end_time, event, []
        )

        assert not errors

    def test_an_empty_slot_must_start_before_it_ends(self):
        errors = PanelService.validate_time_slot(START, START, _event(), [])

        assert errors == ["Start must be before end."]

    def test_slots_touching_at_their_edges_do_not_overlap(self):
        neighbours = [
            _Range(START, START + timedelta(hours=1)),
            _Range(START + timedelta(hours=2), START + timedelta(hours=3)),
        ]

        errors = PanelService.validate_time_slot(
            START + timedelta(hours=1), START + timedelta(hours=2), _event(), neighbours
        )

        assert not errors

    def test_reports_every_violation_at_once(self):
        errors = PanelService.validate_time_slot(
            START - timedelta(hours=1),
            START - timedelta(hours=2),
            _event(),
            [_Range(START - timedelta(hours=3), START)],
        )

        assert errors == [
            "Start must be before end.",
            "Time slot must be within event dates.",
            "Time slot overlaps with an existing slot.",
        ]

    def test_overlap_is_reported_once_however_many_slots_collide(self):
        overlapping = [
            _Range(START, START + timedelta(hours=1)),
            _Range(START + timedelta(minutes=30), START + timedelta(hours=2)),
        ]

        errors = PanelService.validate_time_slot(
            START, START + timedelta(hours=2), _event(), overlapping
        )

        assert errors == ["Time slot overlaps with an existing slot."]
