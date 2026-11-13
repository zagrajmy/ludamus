"""The staff inbox over moderation cases: their mail, their thread, their decision.

A case (`ModerationCase`) holds the notices and chat reports filed under it
and every email about it. Its thread is a staff-only Parley conversation.
Staff talk there through the chat; the server posts its events and email
into it, marked as such.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol, TypedDict

from pydantic import BaseModel, Field

from ludamus.pacts.moderation import (
    CaseStatus,
    ModerationDecision,
    ModerationGround,
    ModerationStatus,
    ModerationVerdict,
    NoticeCategory,
    case_reference,
)
from ludamus.pacts.user import AgeBand

CASE_TITLE_MAX_LENGTH = 200
STAFF_REPLY_MAX_LENGTH = 10_000
STAFF_THREAD_POST_MAX_LENGTH = 4_000


class CaseKind(StrEnum):
    """What opened a case: a notice, a chat report, an email, or staff themselves."""

    NOTICE = "notice"
    CHAT_REPORT = "chat_report"
    EMAIL = "email"
    STATEMENT = "statement"


class CaseEmailDirection(StrEnum):
    IN = "in"
    OUT = "out"


class StaffCaseErrorCode(StrEnum):
    INVALID_BODY = "invalid_body"
    NO_RECIPIENT = "no_recipient"
    INVALID_ASSIGNEE = "invalid_assignee"
    NOTHING_TO_DECIDE = "nothing_to_decide"
    UNDECIDED = "undecided"
    NO_NOTICE = "no_notice"
    UNKNOWN_ACCOUNT = "unknown_account"
    CHAT_UNAVAILABLE = "chat_unavailable"


class StaffMemberDTO(BaseModel):
    pk: int
    name: str


class CaseNoticeDTO(BaseModel):
    pk: int
    url: str
    category: NoticeCategory
    explanation: str
    reporter_name: str
    status: ModerationStatus


class CaseChatReportDTO(BaseModel):
    """A reported chat message, as the report kept it."""

    pk: int
    room_id: str
    reason: str
    reporter_name: str
    author_name: str
    author_age_band: AgeBand | None
    author_joined_at: datetime | None
    body: str
    written_at: datetime | None
    status: ModerationStatus


class CaseVerdictDTO(BaseModel):
    """How the case's records were closed, as the first of them says."""

    status: ModerationStatus
    decision: ModerationDecision
    ground: ModerationGround | None
    decision_text: str


class InboxCaseDTO(BaseModel):
    pk: int
    kind: CaseKind
    status: CaseStatus
    title: str
    child_safety: bool
    assignee_name: str
    created_at: datetime

    @property
    def reference(self) -> str:
        return case_reference(self.pk)


class CaseDTO(InboxCaseDTO):
    assignee_id: int | None
    decided_by_name: str
    thread_id: int | None
    reply_to: str
    reply_name: str
    notices: list[CaseNoticeDTO]
    chat_reports: list[CaseChatReportDTO]
    verdict: CaseVerdictDTO | None


class CaseEmailDTO(BaseModel):
    direction: CaseEmailDirection
    address: str
    name: str
    subject: str
    body: str
    attachments: list[str]
    sent_by_name: str
    created_at: datetime


class CaseDetailDTO(BaseModel):
    case: CaseDTO
    emails: list[CaseEmailDTO]
    staff: list[StaffMemberDTO]
    decidable: bool


class InboundEmail(BaseModel):
    message_id: str
    from_address: str
    from_name: str
    subject: str
    body: str
    attachments: list[str]


class StaffEmailOutcome(StrEnum):
    ATTACHED = "attached"
    OPENED = "opened"
    DUPLICATE = "duplicate"


class StaffEmailReceipt(BaseModel):
    outcome: StaffEmailOutcome
    case_id: int


class StaffDecision(BaseModel):
    """The inbox's decision on a case's open records."""

    decision: ModerationDecision
    ground: ModerationGround | None
    decision_text: str
    legal_provision: str = ""
    suspended_until: date | None = None
    affected_account: str = ""


class CaseOpenedPost(BaseModel):
    event: Literal["case_opened"] = "case_opened"
    kind: CaseKind
    title: str


class EmailInPost(BaseModel):
    event: Literal["email_in"] = "email_in"
    sender: str
    subject: str
    body: str
    attachments: int


class EmailOutPost(BaseModel):
    event: Literal["email_out"] = "email_out"
    staff: StaffMemberDTO
    address: str
    body: str


class NotePost(BaseModel):
    event: Literal["note"] = "note"
    staff: StaffMemberDTO
    body: str


class DecisionPost(BaseModel):
    event: Literal["decision"] = "decision"
    staff: StaffMemberDTO
    status: ModerationStatus
    decision_text: str


type StaffThreadMessage = Annotated[
    CaseOpenedPost | EmailInPost | EmailOutPost | NotePost | DecisionPost,
    Field(discriminator="event"),
]


class StaffThreadEntry(BaseModel):
    """A message the server writes into a case's thread, before it is worded."""

    thread_id: int
    reference: str
    message: StaffThreadMessage
    # Posting the same nonce again adds nothing.
    nonce: str


class StaffThreadPostClaims(BaseModel):
    iss: str
    aud: str
    conversation: str
    author: str
    name: str
    body: str
    nonce: str
    iat: int
    exp: int


class EmailCaseCreateDict(TypedDict):
    title: str
    external_email: str
    external_name: str


class CaseEmailCreateDict(TypedDict):
    case_id: int
    direction: CaseEmailDirection
    message_id: str
    address: str
    name: str
    subject: str
    body: str
    attachments: list[str]
    sent_by_id: int | None


class StaffCaseRepositoryProtocol(Protocol):
    @staticmethod
    def read_staff(user_id: int) -> StaffMemberDTO | None: ...

    @staticmethod
    def list_staff() -> list[StaffMemberDTO]: ...

    @staticmethod
    def open_for_email(data: EmailCaseCreateDict) -> int: ...

    @staticmethod
    def open_thread(case_id: int) -> int: ...

    @staticmethod
    def set_thread_members(
        *, user_ids: list[int], thread_ids: list[int] | None
    ) -> list[int]: ...

    @staticmethod
    def read(case_id: int, *, urgent: frozenset[NoticeCategory]) -> CaseDTO: ...

    @staticmethod
    def list_cases(
        status: CaseStatus,
        *,
        urgent: frozenset[NoticeCategory],
        limit: int,
        offset: int,
    ) -> list[InboxCaseDTO]: ...

    @staticmethod
    def count_by_status() -> dict[CaseStatus, int]: ...

    @staticmethod
    def set_status(*, case_id: int, status: CaseStatus) -> None: ...

    @staticmethod
    def set_assignee(*, case_id: int, assignee_id: int | None) -> None: ...

    @staticmethod
    def set_decided_by(*, case_id: int, user_id: int) -> None: ...

    @staticmethod
    def email_seen(message_id: str) -> int | None: ...

    @staticmethod
    def add_email(data: CaseEmailCreateDict) -> None: ...

    @staticmethod
    def list_emails(case_id: int) -> list[CaseEmailDTO]: ...

    @staticmethod
    def find_account(identifier: str) -> int | None: ...


class StaffThreadProtocol(Protocol):
    def post(self, entry: StaffThreadEntry) -> None: ...


class StaffCaseMailerProtocol(Protocol):
    @staticmethod
    def send_reply(*, to: str, subject: str, body: str, nonce: str) -> None: ...

    @staticmethod
    def verdict_text(verdict: ModerationVerdict) -> str: ...


class StaffCaseServiceProtocol(Protocol):
    def staff(self, *, actor_id: int) -> list[StaffMemberDTO]: ...

    def counts(self, *, actor_id: int) -> dict[CaseStatus, int]: ...

    def cases(
        self, *, actor_id: int, status: CaseStatus, limit: int, offset: int
    ) -> list[InboxCaseDTO]: ...

    def read(self, *, actor_id: int, case_id: int) -> CaseDetailDTO: ...

    def sync_threads(self) -> None: ...

    def receive_email(self, email: InboundEmail) -> StaffEmailReceipt: ...

    def reply(
        self, *, actor_id: int, case_id: int, body: str, by_email: bool
    ) -> None: ...

    def assign(
        self, *, actor_id: int, case_id: int, assignee_id: int | None
    ) -> None: ...

    def close(self, *, actor_id: int, case_id: int) -> None: ...

    def preview(self, decision: StaffDecision) -> str: ...

    def decide(
        self, *, actor_id: int, case_id: int, decision: StaffDecision
    ) -> None: ...


class StaffCaseError(Exception):
    """A case change staff may not make; the code says which."""

    def __init__(self, code: StaffCaseErrorCode) -> None:
        super().__init__(code)
        self.code = code
