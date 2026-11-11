"""What an encounter puts in a calendar: the .ics download and the add-to links."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from ludamus.mills.encounter_calendar import encounter_calendar_links, encounter_ics
from ludamus.pacts.encounter import EncounterDTO

START = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
URL = "https://example.test/e/CODE1"


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


class TestCalendarExports:
    def test_ics_defaults_an_open_ended_encounter_to_two_hours_like_the_invites(self):
        lines = encounter_ics(_encounter(), URL).split("\r\n")

        assert "UID:CODE1@ludamus" in lines
        assert "DTSTART:20260801T180000Z" in lines
        assert "DTEND:20260801T200000Z" in lines
        assert "SUMMARY:Game night" in lines
        assert f"URL:{URL}" in lines
        assert not [line for line in lines if line.startswith("LOCATION")]
        assert not [line for line in lines if line.startswith("DESCRIPTION")]

    def test_ics_prints_end_place_and_description_when_present(self):
        encounter = _encounter(
            end_time=START + timedelta(hours=3), place="Klub", description="Dice"
        )

        lines = encounter_ics(encounter, URL).split("\r\n")

        assert "DTEND:20260801T210000Z" in lines
        assert "LOCATION:Klub" in lines
        assert "DESCRIPTION:Dice" in lines

    def test_google_link_defaults_open_ended_encounter_to_two_hours(self):
        query = _query(encounter_calendar_links(_encounter(), URL).google)

        assert query["dates"] == "20260801T180000Z/20260801T200000Z"

    def test_google_link_keeps_an_explicit_end(self):
        encounter = _encounter(end_time=START + timedelta(hours=3))

        query = _query(encounter_calendar_links(encounter, URL).google)

        assert query["dates"] == "20260801T180000Z/20260801T210000Z"

    def test_outlook_link_defaults_open_ended_encounter_to_two_hours(self):
        query = _query(encounter_calendar_links(_encounter(), URL).outlook)

        assert query["enddt"] == "2026-08-01T20:00:00+00:00"
