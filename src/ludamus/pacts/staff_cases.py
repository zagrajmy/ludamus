"""The staff inbox over moderation cases: their mail, their thread, their decision.

A case (`ModerationCase`) holds the notices and chat reports filed under it
and every email about it. Its thread is a staff-only Parley conversation.
Staff talk there through the chat; the server posts its events and email
into it, marked as such.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from ludamus.pacts.moderation import (
    ModerationDecision,
    ModerationGround,
    ModerationStatus,
    NoticeCategory,
    StatementOfReasons,
    case_reference,
)
from ludamus.pacts.user import AgeBand

CASE_TITLE_MAX_LENGTH = 200
STAFF_REPLY_MAX_LENGTH = 10_000
STAFF_THREAD_POST_MAX_LENGTH = 4_000


class CaseKind(StrEnum):
    """What opened a case: a notice, a chat report, or an email."""

    NOTICE = "notice"
    CHAT_REPORT = "chat_report"
    EMAIL = "email"
    # Staff acted on their own and recorded the statement of reasons.
    STATEMENT = "statement"


class CaseStatus(StrEnum):
    OPEN = "open"
    WAITING = "waiting"
    CLOSED = "closed"


class StaffThreadEvent(StrEnum):
    """What the server writes into a case's thread."""

    CASE_OPENED = "case_opened"
    EMAIL_IN = "email_in"
    EMAIL_OUT = "email_out"
    NOTE = "note"
    DECISION = "decision"


class CaseEmailDirection(StrEnum):
    IN = "in"
    OUT = "out"


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
    involves_minor: bool


class CaseVerdictDTO(BaseModel):
    """How the case's records were closed, as the first of them says."""

    status: ModerationStatus
    decision: ModerationDecision
    ground: ModerationGround | None
    decision_text: str


class CaseRowDTO(BaseModel):
    """A case as the inbox lists it, before mills decide what comes first."""

    pk: int
    status: CaseStatus
    title: str
    assignee_name: str
    created_at: datetime
    has_notices: bool
    has_chat_reports: bool
    opened_by_email: bool
    notice_categories: list[NoticeCategory]
    involves_minor: bool


class CaseDTO(BaseModel):
    pk: int
    status: CaseStatus
    title: str
    assignee_id: int | None
    decided_by_name: str
    thread_id: int | None
    reply_to: str
    reply_name: str
    opened_by_email: bool
    notices: list[CaseNoticeDTO]
    chat_reports: list[CaseChatReportDTO]
    verdict: CaseVerdictDTO | None
    created_at: datetime

    @property
    def reference(self) -> str:
        return case_reference(self.pk)


class CaseEmailDTO(BaseModel):
    direction: CaseEmailDirection
    address: str
    name: str
    subject: str
    body: str
    attachments: list[str]
    sent_by_name: str
    created_at: datetime


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


class StaffInboxDTO(BaseModel):
    status: CaseStatus
    cases: list[InboxCaseDTO]
    counts: dict[CaseStatus, int]


class CaseDetailDTO(BaseModel):
    case: CaseDTO
    kind: CaseKind
    child_safety: bool
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


class StaffThreadEntry(BaseModel):
    """A message the server writes into a case's thread, before it is worded."""

    thread_id: int
    event: StaffThreadEvent
    # The staff member who wrote it; none for a system event or an email in.
    author_id: int | None
    author_name: str
    body: str
    details: dict[str, str]
    # Posting the same nonce again adds nothing.
    nonce: str
    retain_for: timedelta


class StaffThreadPostClaims(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    iss: str
    aud: str
    conversation: str
    author: str
    name: str
    body: str
    source: StaffThreadEvent
    nonce: str
    retain_for: int = Field(serialization_alias="retainFor")
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
    def read(case_id: int) -> CaseDTO: ...

    @staticmethod
    def list_cases(status: CaseStatus) -> list[CaseRowDTO]: ...

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
    def statement_text(statement: StatementOfReasons) -> str: ...


class StaffCaseServiceProtocol(Protocol):
    def inbox(self, *, actor_id: int, status: CaseStatus) -> StaffInboxDTO: ...

    def read(self, *, actor_id: int, case_id: int) -> CaseDetailDTO: ...

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

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
