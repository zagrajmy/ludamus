"""Staff cases: reports, notices, decisions and appeals, each with its thread.

A case's thread is a staff-only Parley conversation. Staff talk there through
the chat; the server posts system events and email into it, marked as such.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from ludamus.pacts.user import AgeBand

STAFF_CASE_REFERENCE_PREFIX = "Z-"
STAFF_CASE_TITLE_MAX_LENGTH = 200
STAFF_REPLY_MAX_LENGTH = 10_000
STAFF_THREAD_POST_MAX_LENGTH = 4_000


def case_reference(number: int) -> str:
    return f"{STAFF_CASE_REFERENCE_PREFIX}{number}"


class StaffCaseKind(StrEnum):
    CHAT_REPORT = "chat_report"
    NOTICE = "notice"
    APPEAL = "appeal"
    EMAIL = "email"


class StaffCaseStatus(StrEnum):
    OPEN = "open"
    WAITING = "waiting"
    CLOSED = "closed"


class ModerationAction(StrEnum):
    NONE = "none"
    HIDE = "hide"
    REMOVE = "remove"
    MUTE_24H = "mute_24h"
    SUSPEND = "suspend"


class ModerationGround(StrEnum):
    """Where a decision stands: a point of the Terms (§ 4.1), or the law."""

    DISRUPTION = "terms_4_1_4"
    MISUSE = "terms_4_1_5"
    RIGHTS = "terms_4_1_6"
    UNLAWFUL_OR_INDECENT = "terms_4_1_7"
    ILLEGAL = "illegal"


class StaffThreadEvent(StrEnum):
    """What the server writes into a case's thread."""

    CASE_OPENED = "case_opened"
    EMAIL_IN = "email_in"
    EMAIL_OUT = "email_out"
    NOTE = "note"
    DECISION = "decision"


class StaffEmailDirection(StrEnum):
    IN = "in"
    OUT = "out"


class StaffMemberDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    name: str


class StaffCaseDecisionDTO(BaseModel):
    action: ModerationAction
    ground: ModerationGround
    decided_by_id: int | None
    decided_by_name: str
    decided_at: datetime


class StaffCaseDTO(BaseModel):
    pk: int
    kind: StaffCaseKind
    status: StaffCaseStatus
    title: str
    child_safety: bool
    assignee_id: int | None
    conversation_id: int
    external_email: str
    external_name: str
    report_id: int | None
    notice_id: int | None
    decision: StaffCaseDecisionDTO | None
    created_at: datetime

    @property
    def reference(self) -> str:
        return case_reference(self.pk)


class StaffCaseListItemDTO(BaseModel):
    pk: int
    kind: StaffCaseKind
    status: StaffCaseStatus
    title: str
    child_safety: bool
    assignee_name: str
    created_at: datetime

    @property
    def reference(self) -> str:
        return case_reference(self.pk)


class ReportedContentDTO(BaseModel):
    """A reported chat message, as the report kept it."""

    room_id: str
    message_id: int
    reason: str
    reporter_name: str
    author_id: int | None
    author_name: str
    author_age_band: AgeBand | None
    author_joined_at: datetime | None
    body: str
    written_at: datetime | None
    deleted_at: datetime | None


class StaffCaseEmailDTO(BaseModel):
    direction: StaffEmailDirection
    address: str
    name: str
    subject: str
    body: str
    attachments: list[str]
    sent_by_name: str
    created_at: datetime


class StaffCaseDetailDTO(BaseModel):
    case: StaffCaseDTO
    content: ReportedContentDTO | None
    emails: list[StaffCaseEmailDTO]
    staff: list[StaffMemberDTO]
    may_decide: bool


class StaffInboxDTO(BaseModel):
    status: StaffCaseStatus
    cases: list[StaffCaseListItemDTO]
    counts: dict[StaffCaseStatus, int]


class ChatReportFacts(BaseModel):
    """What a case needs from a freshly kept chat report."""

    report_id: int
    reason: str
    reporter_name: str
    reporter_email: str
    room_id: str
    involves_minor: bool


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


class StaffThreadEntry(BaseModel):
    """A message the server writes into a case's thread, before it is worded."""

    conversation_id: int
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


class StaffCaseCreateDict(TypedDict):
    kind: StaffCaseKind
    title: str
    child_safety: bool
    conversation_id: int
    external_email: str
    external_name: str
    report_id: int | None


class StaffCaseEmailCreateDict(TypedDict):
    case_id: int
    direction: StaffEmailDirection
    message_id: str
    address: str
    name: str
    subject: str
    body: str
    attachments: list[str]
    sent_by_id: int | None


class StaffCaseDecisionCreateDict(TypedDict):
    case_id: int
    action: ModerationAction
    ground: ModerationGround
    decided_by_id: int


class StaffCaseRepositoryProtocol(Protocol):
    @staticmethod
    def read_staff(user_id: int) -> StaffMemberDTO | None: ...

    @staticmethod
    def list_staff() -> list[StaffMemberDTO]: ...

    @staticmethod
    def create_thread(title: str) -> int: ...

    @staticmethod
    def set_thread_members(
        *, user_ids: list[int], conversation_ids: list[int] | None
    ) -> list[int]: ...

    @staticmethod
    def create(data: StaffCaseCreateDict) -> StaffCaseDTO: ...

    @staticmethod
    def read(case_id: int) -> StaffCaseDTO: ...

    @staticmethod
    def read_for_report(report_id: int) -> StaffCaseDTO | None: ...

    @staticmethod
    def find_chat_report(
        *, reporter_id: int, room_id: str, message_id: int
    ) -> ChatReportFacts | None: ...

    @staticmethod
    def read_content(report_id: int) -> ReportedContentDTO: ...

    @staticmethod
    def list_cases(status: StaffCaseStatus) -> list[StaffCaseListItemDTO]: ...

    @staticmethod
    def count_by_status() -> dict[StaffCaseStatus, int]: ...

    @staticmethod
    def set_status(*, case_id: int, status: StaffCaseStatus) -> None: ...

    @staticmethod
    def set_assignee(*, case_id: int, assignee_id: int | None) -> None: ...

    @staticmethod
    def email_seen(message_id: str) -> int | None: ...

    @staticmethod
    def add_email(data: StaffCaseEmailCreateDict) -> None: ...

    @staticmethod
    def list_emails(case_id: int) -> list[StaffCaseEmailDTO]: ...

    @staticmethod
    def record_decision(data: StaffCaseDecisionCreateDict) -> StaffCaseDecisionDTO: ...


class StaffThreadProtocol(Protocol):
    def post(self, entry: StaffThreadEntry) -> None: ...


class StaffMailerProtocol(Protocol):
    @staticmethod
    def send(*, to: str, subject: str, body: str, nonce: str) -> None: ...


class StaffCaseServiceProtocol(Protocol):
    def inbox(self, *, actor_id: int, status: StaffCaseStatus) -> StaffInboxDTO: ...

    def read(self, *, actor_id: int, case_id: int) -> StaffCaseDetailDTO: ...

    def open_for_chat_report(
        self, *, reporter_id: int, room_id: str, message_id: int
    ) -> StaffCaseDTO | None: ...

    def receive_email(self, email: InboundEmail) -> StaffEmailReceipt: ...

    def reply(
        self, *, actor_id: int, case_id: int, body: str, by_email: bool
    ) -> None: ...

    def assign(
        self, *, actor_id: int, case_id: int, assignee_id: int | None
    ) -> None: ...

    def decide(
        self,
        *,
        actor_id: int,
        case_id: int,
        action: ModerationAction,
        ground: ModerationGround,
    ) -> StaffCaseDecisionDTO: ...


class StaffCaseError(Exception):
    """A case change staff may not make; the code says which."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
