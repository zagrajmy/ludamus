from datetime import UTC, datetime
from http import HTTPStatus

import pytest
from django.urls import reverse
from freezegun import freeze_time

from ludamus.gates.web.django.staging_inbox import (
    LIST_LIMIT,
    CapturedEmail,
    CapturedPart,
    InboxDay,
)
from tests.integration.utils import assert_response, assert_response_404

URL = reverse("web:staging-emails")
SEPARATOR = "-" * 79

RAW_EMAIL = (
    'Content-Type: text/plain; charset="utf-8"\n'
    "Subject: A spot opened\n"
    "From: noreply@zagrajmy.net\n"
    "To: player@example.com\n"
    "Date: Wed, 01 Jul 2026 12:00:00 -0000\n"
    "\n"
    "Claim it before it goes to the next person.\n"
)
SPOT_OPENED = CapturedEmail(
    id="20260701-000000-1-0",
    subject="A spot opened",
    sender="noreply@zagrajmy.net",
    to="player@example.com",
    sent_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
    body="Claim it before it goes to the next person.",
    preview="Claim it before it goes to the next person.",
    links=(),
    parts=(),
    source=RAW_EMAIL.strip(),
)


def _write_email(directory, *, name="20260701-000000-1.log", raw=RAW_EMAIL):
    file = directory / name
    file.write_bytes(raw.encode())
    return file


def _msg(subject, *, to="player@example.com", body="body"):
    return (
        'Content-Type: text/plain; charset="utf-8"\n'
        f"Subject: {subject}\n"
        f"To: {to}\n"
        "\n"
        f"{body}\n"
    )


def _captured(raw, *, email_id, subject, body):
    return CapturedEmail(
        id=email_id,
        subject=subject,
        sender="",
        to="player@example.com",
        sent_at=None,
        body=body,
        preview=body,
        links=(),
        parts=(),
        source=raw.strip(),
    )


def _context(**overrides):
    return {
        "total": 0,
        "newest_id": "",
        "query": "",
        "match_count": 0,
        "days": [],
        "truncated": False,
        "list_limit": LIST_LIMIT,
        "selected": None,
        "requested": "",
    } | overrides


@pytest.fixture(name="inbox")
def inbox_fixture(settings, tmp_path):
    settings.EMAIL_FILE_PATH = str(tmp_path)
    return tmp_path


class TestStagingEmailInboxView:
    def test_404_when_not_file_backend(self, staff_client, settings):
        settings.EMAIL_FILE_PATH = None

        response = staff_client.get(URL)

        assert_response_404(response)

    def test_404_for_non_staff(self, authenticated_client, inbox):
        response = authenticated_client.get(URL)

        assert_response_404(response)

    def test_404_for_anonymous(self, client, inbox):
        response = client.get(URL)

        assert_response_404(response)

    @freeze_time("2026-07-02 09:00")
    def test_ok_empty(self, staff_client, inbox):
        response = staff_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(),
            template_name="staging_email_inbox.html",
        )

    @freeze_time("2026-07-02 09:00")
    def test_ok_opens_newest_email(self, staff_client, inbox):
        _write_email(inbox)

        response = staff_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                total=1,
                newest_id=SPOT_OPENED.id,
                match_count=1,
                days=[InboxDay(label="Yesterday", emails=[SPOT_OPENED])],
                selected=SPOT_OPENED,
            ),
            template_name="staging_email_inbox.html",
        )

    def test_multiple_messages_in_one_file_newest_first(self, staff_client, inbox):
        _write_email(inbox, raw=f"{_msg('Older')}{SEPARATOR}\n{_msg('Newer')}")

        response = staff_client.get(URL)

        days = response.context_data["days"]
        assert [(e.id, e.subject) for day in days for e in day.emails] == [
            ("20260701-000000-1-1", "Newer"),
            ("20260701-000000-1-0", "Older"),
        ]

    @freeze_time("2026-07-02 09:00")
    def test_selects_requested_email(self, staff_client, inbox):
        _write_email(inbox, raw=f"{_msg('Older')}{SEPARATOR}\n{_msg('Newer')}")
        newer = _captured(
            _msg("Newer"), email_id="20260701-000000-1-1", subject="Newer", body="body"
        )
        older = _captured(
            _msg("Older"), email_id="20260701-000000-1-0", subject="Older", body="body"
        )

        response = staff_client.get(URL, {"m": older.id})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                total=2,
                newest_id=newer.id,
                match_count=2,
                days=[InboxDay(label="No date", emails=[newer, older])],
                selected=older,
                requested=older.id,
            ),
            template_name="staging_email_inbox.html",
        )

    @freeze_time("2026-07-02 09:00")
    def test_unknown_requested_email_selects_nothing(self, staff_client, inbox):
        _write_email(inbox)

        response = staff_client.get(URL, {"m": "19990101-000000-1-0"})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                total=1,
                newest_id=SPOT_OPENED.id,
                match_count=1,
                days=[InboxDay(label="Yesterday", emails=[SPOT_OPENED])],
                requested="19990101-000000-1-0",
            ),
            template_name="staging_email_inbox.html",
        )

    def test_search_narrows_list_case_insensitively(self, staff_client, inbox):
        _write_email(
            inbox,
            raw=(
                f"{_msg('Confirm your address', to='new@example.com')}{SEPARATOR}\n"
                f"{_msg('Your address is changing', to='old@example.com')}"
            ),
        )

        response = staff_client.get(URL, {"q": "  NEW@example  "})

        context = response.context_data
        assert context["query"] == "NEW@example"
        assert context["match_count"] == 1
        assert [e.subject for day in context["days"] for e in day.emails] == [
            "Confirm your address"
        ]
        assert context["selected"].subject == "Confirm your address"
        # The header still counts and polls the whole inbox.
        assert (context["total"], context["newest_id"]) == (2, "20260701-000000-1-1")

    @freeze_time("2026-07-02 09:00")
    def test_search_without_matches_selects_nothing(self, staff_client, inbox):
        _write_email(inbox)

        response = staff_client.get(URL, {"q": "nobody"})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(total=1, newest_id=SPOT_OPENED.id, query="nobody"),
            template_name="staging_email_inbox.html",
        )

    @freeze_time("2026-07-02 09:00")
    def test_days_are_labelled_relative_to_today(self, staff_client, inbox):
        def _dated(subject, date_header):
            return _msg(subject).replace("\n\n", f"\nDate: {date_header}\n\n", 1)

        _write_email(
            inbox,
            raw=f"{SEPARATOR}\n".join(
                [
                    _msg("Undated"),
                    _dated("Older", "Mon, 29 Jun 2026 10:00:00 +0000"),
                    _dated("Yesterday's", "Wed, 01 Jul 2026 10:00:00 +0000"),
                    _dated("Today's", "Thu, 02 Jul 2026 08:00:00 +0000"),
                ]
            ),
        )

        response = staff_client.get(URL)

        days = response.context_data["days"]
        assert [(day.label, [e.subject for e in day.emails]) for day in days] == [
            ("Today", ["Today's"]),
            ("Yesterday", ["Yesterday's"]),
            ("Monday, 29 June", ["Older"]),
            ("No date", ["Undated"]),
        ]

    @freeze_time("2026-07-02 09:00")
    def test_unparseable_date_header_reads_as_undated(self, staff_client, inbox):
        raw = _msg("Odd").replace("\n\n", "\nDate: sometime soon\n\n", 1)
        _write_email(inbox, raw=raw)
        odd = _captured(raw, email_id="20260701-000000-1-0", subject="Odd", body="body")

        response = staff_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                total=1,
                newest_id=odd.id,
                match_count=1,
                days=[InboxDay(label="No date", emails=[odd])],
                selected=odd,
            ),
            template_name="staging_email_inbox.html",
        )

    @freeze_time("2026-07-02 09:00")
    def test_missing_mail_directory_reads_as_empty(
        self, staff_client, settings, tmp_path
    ):
        settings.EMAIL_FILE_PATH = str(tmp_path / "not-created-yet")

        response = staff_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(),
            template_name="staging_email_inbox.html",
        )

    def test_list_stops_at_limit(self, staff_client, inbox):
        messages = [_msg(f"Mail {n}") for n in range(LIST_LIMIT + 1)]
        _write_email(inbox, raw=f"{SEPARATOR}\n".join(messages))

        response = staff_client.get(URL)

        context = response.context_data
        assert context["truncated"] is True
        assert context["match_count"] == LIST_LIMIT + 1
        assert sum(len(day.emails) for day in context["days"]) == LIST_LIMIT

    def test_links_extracted_without_trailing_punctuation(self, staff_client, inbox):
        body = (
            "Confirm: https://example.com/crowd/email/link/abc.\n"
            "(Or https://example.com/help), and https://example.com/crowd/email/link/abc"
        )
        _write_email(inbox, raw=_msg("Confirm", body=body))

        response = staff_client.get(URL)

        selected = response.context_data["selected"]
        assert selected.links == (
            "https://example.com/crowd/email/link/abc",
            "https://example.com/help",
        )

    def test_calendar_alternative_listed_as_part(self, staff_client, inbox):
        _write_email(
            inbox,
            raw=(
                "MIME-Version: 1.0\n"
                'Content-Type: multipart/alternative; boundary="b"\n'
                "Subject: Invitation: Dragons\n"
                "To: player@example.com\n"
                "\n"
                "--b\n"
                'Content-Type: text/plain; charset="utf-8"\n'
                "\n"
                "See you there.\n"
                "--b\n"
                'Content-Type: text/calendar; method="REQUEST"; charset="utf-8"\n'
                "\n"
                "BEGIN:VCALENDAR\n"
                "END:VCALENDAR\n"
                "--b--\n"
            ),
        )

        response = staff_client.get(URL)

        selected = response.context_data["selected"]
        assert selected.body == "See you there."
        assert selected.parts == (
            CapturedPart(content_type="text/calendar", filename=""),
        )

    def test_non_ascii_body_decoded(self, staff_client, inbox):
        _write_email(
            inbox,
            raw=(
                'Content-Type: text/plain; charset="utf-8"\n'
                "Content-Transfer-Encoding: 8bit\n"
                "MIME-Version: 1.0\n"
                "Subject: A spot opened =?utf-8?b?4oCU?= claim it\n"
                "To: =?utf-8?b?Z2/Fm8SH?=@example.com\n"
                "\n"
                "Zajmij miejsce — zanim przepadnie.\n"
            ),
        )

        response = staff_client.get(URL)

        selected = response.context_data["selected"]
        assert (selected.subject, selected.to, selected.body, selected.sent_at) == (
            "A spot opened — claim it",
            "gość@example.com",
            "Zajmij miejsce — zanim przepadnie.",
            None,
        )
