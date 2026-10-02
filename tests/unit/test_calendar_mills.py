from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from ludamus.mills.calendar import google_calendar_url, outlook_calendar_url
from ludamus.pacts.calendar import (
    PRODID,
    CalendarEntry,
    ics_document,
    ics_escape,
    ics_utc,
)

START = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
STAMP = datetime(2026, 7, 1, 9, 30, tzinfo=UTC)
URL = "https://example.test/e/CODE1"


def _entry(**overrides):
    fields = {"uid": "CODE1@ludamus", "title": "Gloomhaven", "start": START, "url": URL}
    return CalendarEntry(**{**fields, **overrides})


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


class TestIcsPrimitives:
    def test_escape_protects_every_ics_delimiter(self):
        assert ics_escape("a\\b;c,d\ne") == "a\\\\b\\;c\\,d\\ne"

    def test_utc_converts_a_local_time_before_formatting(self):
        warsaw = datetime(2026, 8, 1, 20, 0, tzinfo=timezone(timedelta(hours=2)))

        assert ics_utc(warsaw) == "20260801T180000Z"


class TestIcsDocument:
    def test_minimal_entry_prints_only_the_required_lines(self):
        document = ics_document(_entry(), stamped_at=STAMP)

        assert document == (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            f"PRODID:{PRODID}\r\nBEGIN:VEVENT\r\n"
            "UID:CODE1@ludamus\r\nDTSTAMP:20260701T093000Z\r\n"
            "DTSTART:20260801T180000Z\r\nSUMMARY:Gloomhaven\r\n"
            f"URL:{URL}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )

    def test_optional_fields_print_escaped(self):
        entry = _entry(
            end=START + timedelta(hours=2),
            location="Klub, sala 2",
            description="Line 1\nLine 2",
        )

        lines = ics_document(entry, stamped_at=STAMP).split("\r\n")

        assert "DTEND:20260801T200000Z" in lines
        assert "LOCATION:Klub\\, sala 2" in lines
        assert "DESCRIPTION:Line 1\\nLine 2" in lines


class TestWebCalendarLinks:
    def test_google_open_ended_entry_is_zero_length_with_url_as_details(self):
        query = _query(google_calendar_url(_entry()))

        assert query["action"] == "TEMPLATE"
        assert query["text"] == "Gloomhaven"
        assert query["dates"] == "20260801T180000Z/20260801T180000Z"
        assert query["details"] == URL
        assert "location" not in query

    def test_google_full_entry_carries_end_location_and_description(self):
        entry = _entry(
            end=START + timedelta(hours=1), location="Klub", description="Bring dice"
        )

        query = _query(google_calendar_url(entry))

        assert query["dates"] == "20260801T180000Z/20260801T190000Z"
        assert query["location"] == "Klub"
        assert query["details"] == f"Bring dice\n\n{URL}"

    def test_outlook_open_ended_entry_is_zero_length(self):
        query = _query(outlook_calendar_url(_entry()))

        assert query["rru"] == "addevent"
        assert query["subject"] == "Gloomhaven"
        assert query["startdt"] == query["enddt"] == "2026-08-01T18:00:00+00:00"
        assert query["body"] == URL
        assert "location" not in query

    def test_outlook_full_entry_carries_end_and_location(self):
        entry = _entry(end=START + timedelta(hours=1), location="Klub")

        query = _query(outlook_calendar_url(entry))

        assert query["enddt"] == "2026-08-01T19:00:00+00:00"
        assert query["location"] == "Klub"
