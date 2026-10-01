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

    def test_strips_scripts_and_unknown_attributes(self):
        html = render_markdown(
            '<script>alert(1)</script><a href="/x" onclick="y">l</a>'
        )

        assert "<script" not in html
        assert "onclick" not in html
        assert '<a href="/x"' in html


class TestCalendarExports:
    def test_ics_carries_uid_start_and_url_but_no_end_for_open_ended(self):
        lines = generate_ics_content(_encounter(), URL).split("\r\n")

        assert "UID:CODE1@ludamus" in lines
        assert "DTSTART:20260801T180000Z" in lines
        assert "SUMMARY:Game night" in lines
        assert f"URL:{URL}" in lines
        assert not [line for line in lines if line.startswith("DTEND")]
        assert not [line for line in lines if line.startswith("LOCATION")]

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


class FakeUow:
    def __init__(self, *, used_fields=()):
        self.session_fields = FakeSessionFields(used=used_fields)


class TestPanelService:
    def test_deletes_an_unused_session_field(self):
        uow = FakeUow()

        assert PanelService(uow).delete_session_field(1)
        assert uow.session_fields.rows == {2}

    def test_keeps_a_session_field_that_a_session_type_requires(self):
        uow = FakeUow(used_fields=[1])

        assert not PanelService(uow).delete_session_field(1)
        assert uow.session_fields.rows == {1, 2}
