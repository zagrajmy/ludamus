"""How the server words a post into a case's thread, and what it signs.

What could go wrong, and so what the tests below check:
- an email or system event shows as written by a staff member, or a staff
  member's words as the system's;
- a decision does not say whether anything was done;
- the Worker gets the chat's retention instead of the case's, or a body it refuses.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.staff_thread import thread_post_claims
from ludamus.pacts.moderation import ModerationStatus
from ludamus.pacts.staff_cases import (
    STAFF_THREAD_POST_MAX_LENGTH,
    CaseKind,
    StaffThreadEntry,
    StaffThreadEvent,
)

NOW = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("_english")


@pytest.fixture
def _english(settings):
    settings.LANGUAGE_CODE = "en"


def _entry(event, **overrides):
    return StaffThreadEntry(
        **{
            "thread_id": 9,
            "event": event,
            "author_id": None,
            "author_name": "",
            "body": "",
            "details": {"reference": "Z-1"},
            "nonce": "n-1",
            "retain_for": timedelta(days=1095),
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("entry", "author", "name", "body"),
    (
        pytest.param(
            _entry(
                StaffThreadEvent.CASE_OPENED,
                body="Spam",
                details={"reference": "Z-1", "kind": CaseKind.CHAT_REPORT},
            ),
            "system",
            "Chat report",
            "Case Z-1 opened: Spam",
            id="chat report opened",
        ),
        pytest.param(
            _entry(
                StaffThreadEvent.CASE_OPENED,
                details={"reference": "Z-2", "kind": CaseKind.STATEMENT},
            ),
            "system",
            "Statement of reasons",
            "Case Z-2 opened: —",
            id="statement case opened",
        ),
        pytest.param(
            _entry(
                StaffThreadEvent.EMAIL_IN,
                author_name="Ola W.",
                body="Mam zrzut.",
                details={"subject": "Re: [Z-1]", "attachments": "2"},
            ),
            "email",
            "Ola W. (email)",
            "Subject: Re: [Z-1]\n\nMam zrzut.\n\n"
            "2 attachments, kept in the staff mailbox",
            id="email in",
        ),
        pytest.param(
            _entry(
                StaffThreadEvent.EMAIL_IN,
                author_name="Ola W.",
                body="Bez załączników.",
                details={"subject": "Hej", "attachments": "0"},
            ),
            "email",
            "Ola W. (email)",
            "Subject: Hej\n\nBez załączników.",
            id="email in without attachments",
        ),
        pytest.param(
            _entry(
                StaffThreadEvent.EMAIL_OUT,
                author_id=4,
                author_name="Piotr",
                body="Dziękujemy.",
                details={"address": "ola@example.com"},
            ),
            "4",
            "Piotr (email)",
            "Sent to ola@example.com:\n\nDziękujemy.",
            id="email out",
        ),
        pytest.param(
            _entry(
                StaffThreadEvent.DECISION,
                author_id=4,
                author_name="Piotr",
                body="Usunięte.",
                details={"status": ModerationStatus.ACTIONED},
            ),
            "4",
            "Piotr",
            "Decided: acted on the content.\n\nUsunięte.",
            id="actioned",
        ),
        pytest.param(
            _entry(
                StaffThreadEvent.DECISION,
                author_id=4,
                author_name="Piotr",
                body="Bez naruszenia.",
                details={"status": ModerationStatus.REJECTED},
            ),
            "4",
            "Piotr",
            "Decided: no action.\n\nBez naruszenia.",
            id="rejected",
        ),
        pytest.param(
            _entry(StaffThreadEvent.NOTE, author_id=4, author_name="Piotr", body="Hm"),
            "4",
            "Piotr",
            "Hm",
            id="note",
        ),
    ),
)
def test_words_each_post_under_its_author(entry, author, name, body):
    claims = thread_post_claims(entry, now=NOW)

    assert (claims.author, claims.name, claims.body) == (author, name, body)


def test_signs_the_case_retention_and_a_body_the_worker_takes():
    entry = _entry(StaffThreadEvent.NOTE, author_id=4, body="x" * 5_000)

    claims = thread_post_claims(entry, now=NOW).model_dump()

    issued = int(NOW.timestamp())
    assert {
        key: claims[key]
        for key in ("aud", "conversation", "retainFor", "iat", "exp", "source")
    } == {
        "aud": "parley-post",
        "conversation": "9",
        "retainFor": 1095 * 86_400,
        "iat": issued,
        "exp": issued + 600,
        "source": StaffThreadEvent.NOTE,
    }
    assert len(claims["body"]) == STAFF_THREAD_POST_MAX_LENGTH
