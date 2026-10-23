"""Reports of illegal content: the notice-and-action flow of DSA Art. 16.

Anyone, signed in or not, can report a piece of user content. A report names
its content by kind and id, so one model serves every kind; adding a kind is
an enum value here, a resolver in the repository and a link on its page. The
reporter gets a receipt at once and the decision later, both by email.
Reports land in one queue for the root sphere's managers.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.ids import SphereId, UserId

REPORT_EXPLANATION_MAX_LENGTH = 5000
REPORT_DECISION_MAX_LENGTH = 2000
REPORTER_NAME_MAX_LENGTH = 255
REPORT_LOCATION_MAX_LENGTH = 2048


class ReportedContentKind(StrEnum):
    SESSION = "session"
    USER = "user"


class ReportReason(StrEnum):
    CHILD_SEXUAL_ABUSE = "child_sexual_abuse"
    THREATS = "threats"
    HATE_SPEECH = "hate_speech"
    PRIVACY = "privacy"
    SCAM = "scam"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    OTHER = "other"

    @property
    def requires_contact(self) -> bool:
        # NOTE: DSA Art. 16(2)(c) lets a notice of child sexual abuse material
        # come without the reporter's name and email.
        return self is not ReportReason.CHILD_SEXUAL_ABUSE


class ReportStatus(StrEnum):
    OPEN = "open"
    DECIDED = "decided"


class ReportRateLimitedError(Exception):
    """The reporter sent too many reports in a short time."""


class ReportAlreadyDecidedError(Exception):
    """A decided report cannot be decided again."""


class ReportIncompleteError(Exception):
    """A submission lacks the good-faith statement or the contact its reason needs."""


class ReportTargetDTO(BaseModel):
    """The reported content as the form names it, and where it lives."""

    kind: ReportedContentKind
    object_id: int
    label: str
    location: str


class ReporterContactDTO(BaseModel):
    name: str
    email: str


class ReportFormDTO(BaseModel):
    target: ReportTargetDTO
    # The signed-in reporter's own name and email, offered as defaults.
    reporter: ReporterContactDTO


class ReportSubmission(BaseModel):
    kind: ReportedContentKind
    object_id: int
    sphere_id: SphereId
    reason: ReportReason
    explanation: str
    reporter_name: str
    reporter_email: str
    reporter_user_id: UserId | None
    # The page the report started from; the target's own page when unknown.
    location: str
    good_faith: bool


class ReportCreateData(BaseModel):
    """A submission after the service checked it, with the target resolved."""

    target: ReportTargetDTO
    sphere_id: SphereId
    reason: ReportReason
    explanation: str
    reporter_name: str
    reporter_email: str
    reporter_user_id: UserId | None
    location: str


class ContentReportDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    kind: ReportedContentKind
    object_id: int
    content_label: str
    location: str
    sphere_name: str
    reason: ReportReason
    explanation: str
    reporter_name: str
    reporter_email: str
    reporter_user_id: UserId | None
    status: ReportStatus
    decision: str
    decided_by_name: str
    decided_at: datetime | None
    decided_automatically: bool
    creation_time: datetime


class ReportReceivedNotification(BaseModel):
    report_id: int
    recipient_user_id: UserId | None
    recipient_email: str
    content_label: str
    location: str
    reason: ReportReason


class ReportDecidedNotification(BaseModel):
    report_id: int
    recipient_user_id: UserId | None
    recipient_email: str
    content_label: str
    decision: str
    decided_automatically: bool


class ReportRepositoryProtocol(Protocol):
    @staticmethod
    def read_target(
        *, kind: ReportedContentKind, object_id: int, sphere_id: SphereId
    ) -> ReportTargetDTO | None: ...
    @staticmethod
    def read_reporter(user_id: UserId) -> ReporterContactDTO: ...
    @staticmethod
    def create(data: ReportCreateData) -> ContentReportDTO: ...
    @staticmethod
    def list_by_status(status: ReportStatus) -> list[ContentReportDTO]: ...
    @staticmethod
    def read(report_id: int) -> ContentReportDTO | None: ...
    @staticmethod
    def lock(report_id: int) -> ContentReportDTO | None: ...
    @staticmethod
    def mark_decided(
        *, report_id: int, decided_by_id: UserId, decision: str, now: datetime
    ) -> ContentReportDTO: ...


class ReportNotifierProtocol(Protocol):
    def notify_report_received(
        self, notification: ReportReceivedNotification
    ) -> None: ...
    def notify_report_decided(
        self, notification: ReportDecidedNotification
    ) -> None: ...


class ReportServiceProtocol(Protocol):
    def prepare(
        self,
        *,
        kind: ReportedContentKind,
        object_id: int,
        sphere_id: SphereId,
        reporter_user_id: UserId | None,
    ) -> ReportFormDTO: ...
    def submit(
        self, submission: ReportSubmission, *, client_ip: str
    ) -> ContentReportDTO: ...


class ReportQueueServiceProtocol(Protocol):
    def list_open(
        self, *, sphere_id: SphereId, root_sphere_id: SphereId
    ) -> list[ContentReportDTO]: ...
    def read(
        self, *, sphere_id: SphereId, root_sphere_id: SphereId, report_id: int
    ) -> ContentReportDTO: ...
    def decide(
        self,
        *,
        sphere_id: SphereId,
        root_sphere_id: SphereId,
        report_id: int,
        decided_by_id: UserId,
        decision: str,
    ) -> ContentReportDTO: ...
