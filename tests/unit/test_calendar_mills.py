from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ludamus.mills.calendar import (
    CalendarEntry,
    google_calendar_url,
    ics_document,
    ics_escape,
    ics_utc,
    outlook_calendar_url,
)

_WARSAW = ZoneInfo("Europe/Warsaw")
_START = datetime(2026, 8, 15, 12, 30, tzinfo=_WARSAW)


def _entry(**overrides):
    values = {
        "uid": "session-7@zagrajmy",
        "title": "Dracula; part 2, act \\1",
        "start": _START,
        "url": "https://zagrajmy.net/s/7",
        "end": _START + timedelta(hours=1, minutes=30),
        "location": "Room 42",
        "description": "Bring dice\nand snacks",
    }
    values.update(overrides)
    return CalendarEntry(**values)


def test_ics_escape_backslashes_separators_and_newlines():
    assert ics_escape("a\\b;c,d\ne") == "a\\\\b\\;c\\,d\\ne"


def test_ics_utc_prints_the_instant_in_utc():
    assert ics_utc(_START) == "20260815T103000Z"


def test_ics_document_lists_every_line_in_order():
    stamped_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

    assert ics_document(_entry(), stamped_at=stamped_at) == (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Zagrajmy//Ludamus//PL\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:session-7@zagrajmy\r\n"
        "DTSTAMP:20260801T090000Z\r\n"
        "DTSTART:20260815T103000Z\r\n"
        "DTEND:20260815T120000Z\r\n"
        "SUMMARY:Dracula\\; part 2\\, act \\\\1\r\n"
        "LOCATION:Room 42\r\n"
        "DESCRIPTION:Bring dice\\nand snacks\r\n"
        "URL:https://zagrajmy.net/s/7\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def test_ics_document_skips_the_optional_lines():
    stamped_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

    document = ics_document(
        _entry(end=None, location="", description=""), stamped_at=stamped_at
    )

    assert document == (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Zagrajmy//Ludamus//PL\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:session-7@zagrajmy\r\n"
        "DTSTAMP:20260801T090000Z\r\n"
        "DTSTART:20260815T103000Z\r\n"
        "SUMMARY:Dracula\\; part 2\\, act \\\\1\r\n"
        "URL:https://zagrajmy.net/s/7\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def test_google_calendar_url_carries_every_field():
    assert google_calendar_url(_entry()) == (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        "&text=Dracula%3B+part+2%2C+act+%5C1"
        "&dates=20260815T103000Z%2F20260815T120000Z"
        "&details=Bring+dice%0Aand+snacks%0A%0Ahttps%3A%2F%2Fzagrajmy.net%2Fs%2F7"
        "&location=Room+42"
    )


def test_google_calendar_url_without_end_or_extras_is_a_point_in_time():
    assert google_calendar_url(_entry(end=None, location="", description="")) == (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        "&text=Dracula%3B+part+2%2C+act+%5C1"
        "&dates=20260815T103000Z%2F20260815T103000Z"
        "&details=https%3A%2F%2Fzagrajmy.net%2Fs%2F7"
    )


def test_outlook_calendar_url_carries_every_field():
    assert outlook_calendar_url(_entry()) == (
        "https://outlook.live.com/calendar/0/action/compose?rru=addevent"
        "&subject=Dracula%3B+part+2%2C+act+%5C1"
        "&startdt=2026-08-15T10%3A30%3A00%2B00%3A00"
        "&enddt=2026-08-15T12%3A00%3A00%2B00%3A00"
        "&body=Bring+dice%0Aand+snacks%0A%0Ahttps%3A%2F%2Fzagrajmy.net%2Fs%2F7"
        "&location=Room+42"
    )


def test_outlook_calendar_url_without_end_or_extras_is_a_point_in_time():
    assert outlook_calendar_url(_entry(end=None, location="", description="")) == (
        "https://outlook.live.com/calendar/0/action/compose?rru=addevent"
        "&subject=Dracula%3B+part+2%2C+act+%5C1"
        "&startdt=2026-08-15T10%3A30%3A00%2B00%3A00"
        "&enddt=2026-08-15T10%3A30%3A00%2B00%3A00"
        "&body=https%3A%2F%2Fzagrajmy.net%2Fs%2F7"
    )
