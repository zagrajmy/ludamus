"""Staff reader for the mail the ``filemail://`` transport captures.

Staging and e2e runs never deliver mail; Django's file backend appends each
message to a ``.log`` file instead. This page is where someone testing a flow
goes to fetch the link a real inbox would have received.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import Http404
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.generic.base import View
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest

# NOTE: Django's filebased backend writes this rule after every message.
_SEPARATOR = b"-" * 79
_URL = re.compile(r"https?://[^\s<>\"']+")
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}'\""
# The list is for finding the mail you just triggered; older mail is reached by
# searching, which scans every captured message.
LIST_LIMIT = 100


class CapturedPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_type: str
    filename: str


class CapturedEmail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    subject: str
    sender: str
    to: str
    sent_at: datetime | None
    body: str
    links: tuple[str, ...]
    parts: tuple[CapturedPart, ...]
    source: str

    @property
    def preview(self) -> str:
        return " ".join(_URL.sub("", self.body).split())

    def matches(self, query: str) -> bool:
        needle = query.casefold()
        return any(
            needle in text.casefold()
            for text in (self.subject, self.to, self.sender, self.body)
        )


class InboxDay(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: date | None
    emails: list[CapturedEmail]


def _links(body: str) -> tuple[str, ...]:
    found = (match.rstrip(_URL_TRAILING_PUNCTUATION) for match in _URL.findall(body))
    return tuple(dict.fromkeys(found))


def _sent_at(header: str) -> datetime | None:
    if not header:
        return None
    try:
        sent_at = parsedate_to_datetime(header)
    except TypeError, ValueError:
        return None
    # NOTE: RFC 5322 reads a "-0000" offset as UTC with no claim about the
    # sender's zone; the stdlib returns that as a naive datetime.
    return sent_at if sent_at.tzinfo else sent_at.replace(tzinfo=UTC)


def _parse(raw: bytes, *, email_id: str) -> CapturedEmail:
    message = message_from_bytes(raw, policy=policy.default)
    body_part = message.get_body(preferencelist=("plain", "html"))
    body = str(body_part.get_content()).strip() if body_part else ""
    parts = tuple(
        CapturedPart(
            content_type=part.get_content_type(), filename=part.get_filename() or ""
        )
        for part in message.walk()
        if not part.is_multipart() and part is not body_part
    )
    return CapturedEmail(
        id=email_id,
        subject=str(message["Subject"] or ""),
        sender=str(message["From"] or ""),
        to=str(message["To"] or ""),
        sent_at=_sent_at(str(message["Date"] or "")),
        body=body,
        links=_links(body),
        parts=parts,
        source=raw.decode(errors="replace"),
    )


def _read_log(log_file: Path) -> list[CapturedEmail]:
    # The backend only ever appends, so a message's position in its file is a
    # stable address for a ?m= link.
    chunks = log_file.read_bytes().split(_SEPARATOR)
    return [
        _parse(raw, email_id=f"{log_file.stem}-{index}")
        for index, chunk in reversed(list(enumerate(chunks)))
        if (raw := chunk.strip())
    ]


def read_captured_emails(directory: Path) -> list[CapturedEmail]:
    """Return every captured message, newest first.

    Returns:
        Parsed messages; empty when nothing has been sent yet.
    """
    if not directory.exists():
        return []
    return [
        email
        for log_file in sorted(directory.glob("*.log"), reverse=True)
        for email in _read_log(log_file)
    ]


def _by_day(emails: list[CapturedEmail]) -> list[InboxDay]:
    return [
        InboxDay(day=day, emails=list(group))
        for day, group in groupby(
            emails,
            key=lambda email: (
                timezone.localdate(email.sent_at) if email.sent_at else None
            ),
        )
    ]


def _selected(
    emails: list[CapturedEmail], *, listed: list[CapturedEmail], requested: str
) -> CapturedEmail | None:
    # `m` picks the open message; without it the newest listed one opens on
    # wide screens and the list alone shows on narrow ones.
    if requested:
        return next((email for email in emails if email.id == requested), None)
    return listed[0] if listed else None


class StagingEmailInboxView(View):
    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        if not settings.EMAIL_FILE_PATH or not request.user.is_staff:
            raise Http404
        emails = read_captured_emails(Path(settings.EMAIL_FILE_PATH))
        query = request.GET.get("q", "").strip()
        matches = [email for email in emails if not query or email.matches(query)]
        listed = matches[:LIST_LIMIT]
        requested = request.GET.get("m", "")
        selected = _selected(emails, listed=listed, requested=requested)
        today = timezone.localdate()
        return TemplateResponse(
            request,
            "staging_email_inbox.html",
            {
                "emails": emails,
                "query": query,
                "match_count": len(matches),
                "days": _by_day(listed),
                "truncated": len(matches) > len(listed),
                "list_limit": LIST_LIMIT,
                "selected": selected,
                "requested": requested,
                "today": today,
                "yesterday": today - timedelta(days=1),
            },
        )
