"""How the server words a post into a case's thread, and what it signs.

What could go wrong, and so what the tests below check:
- a post does not say who or what it is about: the sender, the staff
  member who answered or decided;
- a mail's text reaches the thread, where only staff's words belong;
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
    ("message", "name", "body"),
    (
        pytest.param(
            CaseOpenedPost(kind=CaseKind.CHAT_REPORT, title="Spam"),
            "Chat report",
            "Case Z-1 opened: Spam",
            id="chat report opened",
        ),
        pytest.param(
            CaseOpenedPost(kind=CaseKind.STATEMENT, title=""),
            "Statement of reasons",
            "Case Z-1 opened: —",
            id="statement case opened",
        ),
        pytest.param(
            EmailInPost(sender="Ola W.", subject="Re: [Z-1]"),
            "Ola W. (email)",
            "Subject: Re: [Z-1]",
            id="email in",
        ),
        pytest.param(
            EmailInPost(sender="ola@example.com", subject=""),
            "ola@example.com (email)",
            "Subject: —",
            id="email in without a subject",
        ),
        pytest.param(
            EmailOutPost(staff=PIOTR, address="ola@example.com"),
            "Piotr (email)",
            "Replied to ola@example.com.",
            id="email out",
        ),
        pytest.param(
            DecisionPost(
                staff=PIOTR, status=ModerationStatus.ACTIONED, decision_text="Usunięte."
            ),
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
            "Piotr",
            "Decided: no action.\n\nBez naruszenia.",
            id="rejected",
        ),
    ),
)
def test_words_each_post_under_who_it_is_about(message, name, body):
    claims = thread_post_claims(_entry(message), now=NOW)

    assert (claims.name, claims.body) == (name, body)


def test_signs_a_body_the_worker_takes_for_its_room():
    decision = DecisionPost(
        staff=PIOTR, status=ModerationStatus.ACTIONED, decision_text="x" * 5_000
    )

    claims = thread_post_claims(_entry(decision), now=NOW).model_dump()

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
