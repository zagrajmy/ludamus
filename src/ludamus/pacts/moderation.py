"""Notices of illegal content, staff decisions, and statements of reasons.

What the Digital Services Act asks of a hosting service whatever its size:
an electronic notice anyone can send (Art. 16), and a statement of reasons
to everyone a moderation decision affects (Art. 17). Every notice, chat
report and statement belongs to a case, and every mail about it names the
case's reference, so replies can be filed under it.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

NOTICE_URL_MAX_LENGTH = 2048
NOTICE_EXPLANATION_MAX_LENGTH = 5000
NOTICE_NAME_MAX_LENGTH = 255
DECISION_TEXT_MAX_LENGTH = 5000
LEGAL_PROVISION_MAX_LENGTH = 255


def case_reference(case_id: int) -> str:
    return f"Z-{case_id}"


class NoticeCategory(StrEnum):
    CHILD_SEXUAL_ABUSE = "child_sexual_abuse"
    CHILD_SAFETY = "child_safety"
    THREATS_OR_HATE = "threats_or_hate"
    HARASSMENT = "harassment"
    PRIVACY = "privacy"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    FRAUD = "fraud"
    OTHER = "other"


class ModerationStatus(StrEnum):
    OPEN = "open"
    ACTIONED = "actioned"
    REJECTED = "rejected"


class ModerationDecision(StrEnum):
    NO_ACTION = "no_action"
    WARNING = "warning"
    CONTENT_REMOVED = "content_removed"
    ACCOUNT_SUSPENDED = "account_suspended"
    ACCOUNT_REMOVED = "account_removed"


class ModerationGround(StrEnum):
    """Why content or an account was acted on: the law, or a point of § 4.1."""

    ILLEGAL_CONTENT = "illegal_content"
    TERMS_FALSE_DATA = "terms_4_1_1"
    TERMS_MULTIPLE_ACCOUNTS = "terms_4_1_2"
    TERMS_FAKE_SIGNUPS = "terms_4_1_3"
    TERMS_DISRUPTION = "terms_4_1_4"
    TERMS_MISUSE = "terms_4_1_5"
    TERMS_OTHERS_RIGHTS = "terms_4_1_6"
    TERMS_UNLAWFUL_CONTENT = "terms_4_1_7"
    TERMS_UNAUTHORISED_ACCESS = "terms_4_1_8"


class CaseStatus(StrEnum):
    """Where a case stands for staff, apart from how its records were decided."""

    OPEN = "open"
    # Staff answered and wait on the other side.
    WAITING = "waiting"
    CLOSED = "closed"


class ModerationSource(StrEnum):
    NOTICE = "notice"
    CHAT_REPORT = "chat_report"


class NoticeOutcome(StrEnum):
    CREATED = "created"
    THROTTLED = "throttled"
    CONTACT_REQUIRED = "contact_required"


class InvalidVerdictError(Exception):
    """A decision that does not hold together, such as an action with no ground."""


class ContentNoticeData(BaseModel):
    url: str
    category: NoticeCategory
    explanation: str
    reporter_name: str
    reporter_email: str
    reporter_id: int | None
    sphere_id: int
    language: str


class ContentNoticeSubmission(BaseModel):
    outcome: NoticeOutcome
    case_reference: str = ""


class ContentNoticeCreateDict(TypedDict):
    case_id: int
    url: str
    category: NoticeCategory
    explanation: str
    reporter_name: str
    reporter_email: str
    reporter_id: int | None
    sphere_id: int
    language: str


class ContentNoticeDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    case_id: int | None
    url: str
    category: NoticeCategory
    explanation: str
    reporter_email: str
    language: str
    status: ModerationStatus


class ChatReportDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    case_id: int | None
    reporter_id: int
    reported_user_id: int | None
    room_id: str
    message_id: int
    author_name: str
    body: str
    reason: str
    status: ModerationStatus


class ModerationVerdict(BaseModel):
    status: ModerationStatus
    decision: ModerationDecision
    ground: ModerationGround | None
    decision_text: str
    # Art. 17(3)(d): the provision broken, when the ground is the law.
    legal_provision: str = ""
    # Art. 17(3)(a): how long a suspension lasts.
    suspended_until: date | None = None


class ModerationDecisionDict(TypedDict):
    status: ModerationStatus
    decision: ModerationDecision
    ground: str
    legal_provision: str
    suspended_until: date | None
    decision_text: str
    resolved_at: datetime


class StatementOfReasons(BaseModel):
    user_id: int
    case_id: int | None
    decision: ModerationDecision
    ground: ModerationGround
    facts: str
    from_report: bool
    legal_provision: str = ""
    suspended_until: date | None = None
    # NOTE: Art. 17(3)(c) asks whether automated means were used; none are yet.
    automated: bool = False


class StatementOfReasonsCreateDict(TypedDict):
    case_id: int
    user_id: int
    decision: ModerationDecision
    ground: ModerationGround
    legal_provision: str
    suspended_until: date | None
    facts: str
    from_report: bool
    automated: bool


class IssuedStatement(BaseModel):
    case_id: int
    user_id: int
    # False when the account has no address on record to mail.
    mailed: bool


class ModerationDecisionsDTO(BaseModel):
    decided: int
    statements: list[IssuedStatement]


class StaffAlert(BaseModel):
    case_id: int
    source: ModerationSource
    record_id: int
    category: NoticeCategory | None
    urgent: bool
    location: str
    explanation: str


class NoticeReceipt(BaseModel):
    case_id: int
    address: str
    language: str
    category: NoticeCategory


class ReporterOutcome(BaseModel):
    case_id: int
    status: ModerationStatus
    decision_text: str
    reporter_id: int | None = None
    address: str = ""
    language: str = ""


class ModerationCaseRepositoryProtocol(Protocol):
    @staticmethod
    def open(*, status: CaseStatus) -> int: ...


class ContentNoticeRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ContentNoticeCreateDict) -> ContentNoticeDTO: ...
    @staticmethod
    def read(pk: int) -> ContentNoticeDTO: ...
    @staticmethod
    def decide(pk: int, decision: ModerationDecisionDict) -> bool: ...


class ChatReportRepositoryProtocol(Protocol):
    @staticmethod
    def read_by_message(
        *, reporter_id: int, room_id: str, message_id: int
    ) -> ChatReportDTO | None: ...
    @staticmethod
    def read(pk: int) -> ChatReportDTO: ...

    # The case another report of the same message is filed under, if any.
    @staticmethod
    def case_of_message(*, room_id: str, message_id: int) -> int | None: ...
    @staticmethod
    def attach_case(*, pk: int, case_id: int) -> bool: ...
    @staticmethod
    def decide(pk: int, decision: ModerationDecisionDict) -> bool: ...


class StatementOfReasonsRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: StatementOfReasonsCreateDict) -> int: ...
    @staticmethod
    def exists(*, case_id: int, user_id: int) -> bool: ...


class ActiveRecipientsRepositoryProtocol(Protocol):
    @staticmethod
    def count_active_accounts(*, start: datetime, end: datetime) -> int: ...


class ModerationMailerProtocol(Protocol):
    @staticmethod
    def alert_staff(alert: StaffAlert) -> None: ...
    @staticmethod
    def send_receipt(receipt: NoticeReceipt) -> None: ...
    @staticmethod
    def send_outcome(outcome: ReporterOutcome) -> None: ...
    @staticmethod
    def send_statement(*, statement: StatementOfReasons, case_id: int) -> bool: ...


class MonthlyActiveRecipientsDTO(BaseModel):
    months: list[tuple[datetime, int]]
    average: float


class NoticeServiceProtocol(Protocol):
    def submit(
        self, data: ContentNoticeData, *, ip_address: str
    ) -> ContentNoticeSubmission: ...


class ChatReportIntakeServiceProtocol(Protocol):
    def take(self, *, reporter_id: int, room_id: str, message_id: int) -> None: ...


class StatementOfReasonsServiceProtocol(Protocol):
    def issue(self, statement: StatementOfReasons) -> IssuedStatement | None: ...


class ModerationDecisionServiceProtocol(Protocol):
    def check(self, verdict: ModerationVerdict) -> None: ...
    def decide_notices(
        self,
        *,
        notice_ids: list[int],
        verdict: ModerationVerdict,
        affected_user_id: int | None,
    ) -> ModerationDecisionsDTO: ...
    def decide_chat_reports(
        self, *, report_ids: list[int], verdict: ModerationVerdict
    ) -> ModerationDecisionsDTO: ...


class ActiveRecipientsServiceProtocol(Protocol):
    def monthly_average(self, *, now: datetime) -> MonthlyActiveRecipientsDTO: ...
