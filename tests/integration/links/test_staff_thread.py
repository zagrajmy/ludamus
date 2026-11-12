"""How the server words a post into a case's thread, and what it signs.

What could go wrong, and so what the tests below check:
- an email or system event shows as written by a staff member, or a staff
  member's words as the system's;
- a decision names its action or ground by code instead of words;
- the Worker gets the chat's retention instead of the case's, or a body it refuses.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.staff_thread import thread_post_claims
from ludamus.pacts.staff_cases import (
    STAFF_THREAD_POST_MAX_LENGTH,
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
            "conversation_id": 9,
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
                details={"room": "organizers:3"},
            ),
            "system",
            "Chat report",
            "Reported in organizers:3. Reason: Spam",
            id="case opened",
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
                details={"action": "mute_24h", "ground": "illegal"},
            ),
            "4",
            "Piotr",
            "Decision: Mute for 24 hours. Ground: Illegal content.",
            id="decision",
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
