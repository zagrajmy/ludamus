"""Reports of illegal content: taking a notice in, and deciding it.

`ReportService` is the public side: anyone may report what they see in the
current sphere. `ReportQueueService` is the root sphere's queue; every method
refuses any other sphere, so a report id reaches nothing from there.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.report import (
    ReportAlreadyDecidedError,
    ReportCreateData,
    ReportDecidedNotification,
    ReporterContactDTO,
    ReportFormDTO,
    ReportIncompleteError,
    ReportQueueServiceProtocol,
    ReportRateLimitedError,
    ReportReceivedNotification,
    ReportServiceProtocol,
    ReportStatus,
)
from ludamus.specs.report import REPORT_WINDOW_SECONDS, REPORTS_PER_WINDOW

if TYPE_CHECKING:
    from ludamus.pacts import CacheProtocol
    from ludamus.pacts.ids import SphereId, UserId
    from ludamus.pacts.report import (
        ContentReportDTO,
        ReportedContentKind,
        ReportNotifierProtocol,
        ReportRepositoryProtocol,
        ReportSubmission,
        ReportTargetDTO,
    )
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


def _rate_key(*, user_id: UserId | None, client_ip: str) -> str:
    if user_id is not None:
        return f"report_rate:user:{user_id}"
    return f"report_rate:ip:{client_ip}"


class ReportService(ReportServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        reports: ReportRepositoryProtocol,
        cache: CacheProtocol,
        notifier: ReportNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._reports = reports
        self._cache = cache
        self._notifier = notifier

    def _target(
        self, *, kind: ReportedContentKind, object_id: int, sphere_id: SphereId
    ) -> ReportTargetDTO:
        target = self._reports.read_target(
            kind=kind, object_id=object_id, sphere_id=sphere_id
        )
        if target is None:
            raise NotFoundError
        return target

    def prepare(
        self,
        *,
        kind: ReportedContentKind,
        object_id: int,
        sphere_id: SphereId,
        reporter_user_id: UserId | None,
    ) -> ReportFormDTO:
        return ReportFormDTO(
            target=self._target(kind=kind, object_id=object_id, sphere_id=sphere_id),
            reporter=(
                ReporterContactDTO(name="", email="")
                if reporter_user_id is None
                else self._reports.read_reporter(reporter_user_id)
            ),
        )

    def submit(
        self, submission: ReportSubmission, *, client_ip: str
    ) -> ContentReportDTO:
        target = self._target(
            kind=submission.kind,
            object_id=submission.object_id,
            sphere_id=submission.sphere_id,
        )
        name = submission.reporter_name.strip()
        email = submission.reporter_email.strip()
        if not submission.good_faith or (
            submission.reason.requires_contact and not (name and email)
        ):
            raise ReportIncompleteError

        key = _rate_key(user_id=submission.reporter_user_id, client_ip=client_ip)
        sent = self._cache.get(key)
        if (count := sent if isinstance(sent, int) else 0) >= REPORTS_PER_WINDOW:
            logger.warning(
                "Content report refused by rate limit: kind=%s content=%s signed_in=%s",
                target.kind,
                target.object_id,
                submission.reporter_user_id is not None,
            )
            raise ReportRateLimitedError

        with self._transaction.atomic():
            report = self._reports.create(
                ReportCreateData(
                    target=target,
                    sphere_id=submission.sphere_id,
                    reason=submission.reason,
                    explanation=submission.explanation.strip(),
                    reporter_name=name,
                    reporter_email=email,
                    reporter_user_id=submission.reporter_user_id,
                    location=submission.location or target.location,
                )
            )
            self._notifier.notify_report_received(
                ReportReceivedNotification(
                    report_id=report.pk,
                    recipient_user_id=report.reporter_user_id,
                    recipient_email=report.reporter_email,
                    content_label=report.content_label,
                    location=report.location,
                    reason=report.reason,
                )
            )
        self._cache.set(key, count + 1, timeout=REPORT_WINDOW_SECONDS)
        logger.info(
            "Content report received: report=%s kind=%s content=%s reason=%s "
            "signed_in=%s",
            report.pk,
            report.kind,
            report.object_id,
            report.reason,
            report.reporter_user_id is not None,
        )
        return report


class ReportQueueService(ReportQueueServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        reports: ReportRepositoryProtocol,
        notifier: ReportNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._reports = reports
        self._notifier = notifier

    @staticmethod
    def _require_root(*, sphere_id: SphereId, root_sphere_id: SphereId) -> None:
        # NOTE: one queue for the platform (#1566): a reporter's contact
        # details stay with the root team, never with the sphere whose
        # organisers may be the people reported.
        if sphere_id != root_sphere_id:
            raise NotFoundError

    def list_open(
        self, *, sphere_id: SphereId, root_sphere_id: SphereId
    ) -> list[ContentReportDTO]:
        self._require_root(sphere_id=sphere_id, root_sphere_id=root_sphere_id)
        return self._reports.list_by_status(ReportStatus.OPEN)

    def read(
        self, *, sphere_id: SphereId, root_sphere_id: SphereId, report_id: int
    ) -> ContentReportDTO:
        self._require_root(sphere_id=sphere_id, root_sphere_id=root_sphere_id)
        if (report := self._reports.read(report_id)) is None:
            raise NotFoundError
        return report

    def decide(
        self,
        *,
        sphere_id: SphereId,
        root_sphere_id: SphereId,
        report_id: int,
        decided_by_id: UserId,
        decision: str,
    ) -> ContentReportDTO:
        self._require_root(sphere_id=sphere_id, root_sphere_id=root_sphere_id)
        with self._transaction.atomic():
            # Locked, so two managers deciding at once send one decision.
            if (report := self._reports.lock(report_id)) is None:
                raise NotFoundError
            if report.status is ReportStatus.DECIDED:
                raise ReportAlreadyDecidedError
            decided = self._reports.mark_decided(
                report_id=report_id,
                decided_by_id=decided_by_id,
                decision=decision.strip(),
                now=datetime.now(tz=UTC),
            )
            self._notifier.notify_report_decided(
                ReportDecidedNotification(
                    report_id=decided.pk,
                    recipient_user_id=decided.reporter_user_id,
                    recipient_email=decided.reporter_email,
                    content_label=decided.content_label,
                    decision=decided.decision,
                    decided_automatically=decided.decided_automatically,
                )
            )
        logger.info(
            "Content report decided: report=%s by=%s automated=%s",
            decided.pk,
            decided_by_id,
            decided.decided_automatically,
        )
        return decided
