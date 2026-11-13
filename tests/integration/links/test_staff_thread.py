"""How the server words a post into a case's thread, and what it signs.

What could go wrong, and so what the tests below check:
- an email or system event shows as written by a staff member, or a staff
  member's words as the system's;
- a decision does not say whether anything was done;
- the Worker gets a body longer than it takes.
"""

from datetime import UTC, datetime

import pytest

from ludamus.links.db.django.staff_thread import thread_post_claims
from ludamus.pacts.moderation import ModerationStatus
from ludamus.pacts.staff_cases import (
    STAFF_THREAD_POST_MAX_LENGTH,
    CaseKind,
    CaseOpenedPost,
    DecisionPost,
    EmailInPost,
    EmailOutPost,
    NotePost,
    StaffMemberDTO,
    StaffThreadEntry,
)

NOW = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)
PIOTR = StaffMemberDTO(pk=4, name="Piotr")

pytestmark = pytest.mark.usefixtures("_english")


@pytest.fixture
def _english(settings):
    settings.LANGUAGE_CODE = "en"


def _entry(message):
    return StaffThreadEntry(thread_id=9, reference="Z-1", message=message, nonce="n-1")


@pytest.mark.parametrize(
    ("message", "author", "name", "body"),
    (
        pytest.param(
            CaseOpenedPost(kind=CaseKind.CHAT_REPORT, title="Spam"),
            "system",
            "Chat report",
            "Case Z-1 opened: Spam",
            id="chat report opened",
        ),
        pytest.param(
            CaseOpenedPost(kind=CaseKind.STATEMENT, title=""),
            "system",
            "Statement of reasons",
            "Case Z-1 opened: —",
            id="statement case opened",
        ),
        pytest.param(
            EmailInPost(
                sender="Ola W.", subject="Re: [Z-1]", body="Mam zrzut.", attachments=2
            ),
            "email",
            "Ola W. (email)",
            "Subject: Re: [Z-1]\n\nMam zrzut.\n\n"
            "2 attachments, kept in the staff mailbox",
            id="email in",
        ),
        pytest.param(
            EmailInPost(sender="Ola W.", subject="Hej", body="Treść.", attachments=0),
            "email",
            "Ola W. (email)",
            "Subject: Hej\n\nTreść.",
            id="email in without attachments",
        ),
        pytest.param(
            EmailOutPost(staff=PIOTR, address="ola@example.com", body="Dziękujemy."),
            "4",
            "Piotr (email)",
            "Sent to ola@example.com:\n\nDziękujemy.",
            id="email out",
        ),
        pytest.param(
            DecisionPost(
                staff=PIOTR, status=ModerationStatus.ACTIONED, decision_text="Usunięte."
            ),
            "4",
            "Piotr",
            "Decided: acted on the content.\n\nUsunięte.",
            id="actioned",
        ),
        pytest.param(
            DecisionPost(
                staff=PIOTR,
                status=ModerationStatus.REJECTED,
                decision_text="Bez naruszenia.",
            ),
            "4",
            "Piotr",
            "Decided: no action.\n\nBez naruszenia.",
            id="rejected",
        ),
        pytest.param(NotePost(staff=PIOTR, body="Hm"), "4", "Piotr", "Hm", id="note"),
    ),
)
def test_words_each_post_under_its_author(message, author, name, body):
    claims = thread_post_claims(_entry(message), now=NOW)

    assert (claims.author, claims.name, claims.body) == (author, name, body)


def test_signs_a_body_the_worker_takes_for_its_room():
    claims = thread_post_claims(
        _entry(NotePost(staff=PIOTR, body="x" * 5_000)), now=NOW
    ).model_dump()

    issued = int(NOW.timestamp())
    assert {
        key: claims[key] for key in ("aud", "conversation", "nonce", "iat", "exp")
    } == {
        "aud": "parley-post",
        "conversation": "9",
        "nonce": "n-1",
        "iat": issued,
        "exp": issued + 600,
    }
    assert len(claims["body"]) == STAFF_THREAD_POST_MAX_LENGTH
