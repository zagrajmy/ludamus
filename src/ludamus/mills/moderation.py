from __future__ import annotations

import ipaddress
import logging
from datetime import UTC, datetime
from hashlib import sha256
from itertools import pairwise
from typing import TYPE_CHECKING

from ludamus.pacts.moderation import (
    ContentNoticeSubmission,
    InvalidVerdictError,
    IssuedStatement,
    ModerationDecision,
    ModerationDecisionDict,
    ModerationDecisionsDTO,
    ModerationGround,
    ModerationSource,
    ModerationStatus,
    MonthlyActiveRecipientsDTO,
    NoticeOutcome,
    NoticeReceipt,
    ReporterOutcome,
    StaffAlert,
    StatementOfReasons,
    case_reference,
)
from ludamus.specs.moderation import (
    ACTIVE_RECIPIENT_MONTHS,
    ANONYMOUS_NOTICE_CATEGORIES,
    NOTICE_WINDOW_SECONDS,
    NOTICES_PER_ADDRESS,
    RECEIPT_WINDOW_SECONDS,
    RECEIPTS_PER_ADDRESS,
    URGENT_NOTICE_CATEGORIES,
)

if TYPE_CHECKING:
    from datetime import date

    from ludamus.pacts.cache import CounterProtocol
    from ludamus.pacts.moderation import (
        ActiveRecipientsRepositoryProtocol,
        ChatReportRepositoryProtocol,
        ContentNoticeData,
        ContentNoticeRepositoryProtocol,
        ModerationCaseRepositoryProtocol,
        ModerationMailerProtocol,
        ModerationVerdict,
        StatementOfReasonsRepositoryProtocol,
        StatementOfReasonsServiceProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


class NoticeService:
    """Take a notice of illegal content from anyone, signed in or not."""

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        cases: ModerationCaseRepositoryProtocol,
        notices: ContentNoticeRepositoryProtocol,
        counter: CounterProtocol,
        mailer: ModerationMailerProtocol,
    ) -> None:
        self._transaction = transaction
        self._cases = cases
        self._notices = notices
        self._counter = counter
        self._mailer = mailer

    def submit(
        self, data: ContentNoticeData, *, ip_address: str
    ) -> ContentNoticeSubmission:
        name, email = data.reporter_name.strip(), data.reporter_email.strip()
        if data.category not in ANONYMOUS_NOTICE_CATEGORIES and not (name and email):
            return ContentNoticeSubmission(outcome=NoticeOutcome.CONTACT_REQUIRED)
        if self._over_limit(ip_address):
            logger.warning(
                "Content notice throttled", extra={"sphere_id": data.sphere_id}
            )
            return ContentNoticeSubmission(outcome=NoticeOutcome.THROTTLED)
        urgent = data.category in URGENT_NOTICE_CATEGORIES
        with self._transaction.atomic():
            case_id = self._cases.open()
            notice = self._notices.create(
                {
                    "case_id": case_id,
                    "url": data.url.strip(),
                    "category": data.category,
                    "explanation": data.explanation.strip(),
                    "reporter_name": name,
                    "reporter_email": email,
                    "reporter_id": data.reporter_id,
                    "sphere_id": data.sphere_id,
                    "language": data.language,
                }
            )
            self._mailer.alert_staff(
                StaffAlert(
                    case_id=case_id,
                    source=ModerationSource.NOTICE,
                    record_id=notice.pk,
                    category=data.category,
                    urgent=urgent,
                    location=notice.url,
                    explanation=notice.explanation,
                )
            )
            if email and self._may_receipt(email):
                self._mailer.send_receipt(
                    NoticeReceipt(
                        case_id=case_id,
                        address=email,
                        language=data.language,
                        category=data.category,
                    )
                )
        logger.info(
            "Content notice received",
            extra={
                "case": case_reference(case_id),
                "category": data.category.value,
                "urgent": urgent,
                "anonymous": not email,
                "sphere_id": data.sphere_id,
            },
        )
        return ContentNoticeSubmission(
            outcome=NoticeOutcome.CREATED, case_reference=case_reference(case_id)
        )

    def _over_limit(self, client_ip: str) -> bool:
        key = f"content_notice_rate:{_digest(_sender(client_ip))}"
        hits = self._counter.hit(key, window_seconds=NOTICE_WINDOW_SECONDS)
        return hits > NOTICES_PER_ADDRESS

    def _may_receipt(self, email: str) -> bool:
        # The address is typed by whoever sends the form, so it may be
        # someone else's; receipts to one address are capped.
        key = f"content_notice_receipt:{_digest(email.casefold())}"
        if self._counter.hit(key, window_seconds=RECEIPT_WINDOW_SECONDS) > (
            RECEIPTS_PER_ADDRESS
        ):
            logger.warning("Notice receipt withheld: address over its daily cap")
            return False
        return True


def _sender(client_ip: str) -> str:
    """Name the sender by address; an IPv6 one by its /64, which one host holds."""
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return client_ip
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network(f"{address}/64", strict=False).network_address)
    return str(address)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


class ChatReportIntakeService:
    """Open a case for a chat report and tell staff it arrived."""

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        cases: ModerationCaseRepositoryProtocol,
        reports: ChatReportRepositoryProtocol,
        mailer: ModerationMailerProtocol,
    ) -> None:
        self._transaction = transaction
        self._cases = cases
        self._reports = reports
        self._mailer = mailer

    def take(self, *, reporter_id: int, room_id: str, message_id: int) -> None:
        with self._transaction.atomic():
            report = self._reports.read_by_message(
                reporter_id=reporter_id, room_id=room_id, message_id=message_id
            )
            if report is None or report.case_id is not None:
                return
            # Everyone reporting one message joins one case, so its author
            # gets one statement however many people reported it.
            shared = self._reports.case_of_message(
                room_id=room_id, message_id=message_id
            )
            case_id = shared if shared is not None else self._cases.open()
            if not self._reports.attach_case(pk=report.pk, case_id=case_id):
                return
            if shared is not None:
                logger.info(
                    "Chat report joined its message's case",
                    extra={"case": case_reference(case_id), "report_id": report.pk},
                )
                return
            self._mailer.alert_staff(
                StaffAlert(
                    case_id=case_id,
                    source=ModerationSource.CHAT_REPORT,
                    record_id=report.pk,
                    category=None,
                    urgent=False,
                    location=report.room_id,
                    explanation=report.reason,
                )
            )
        logger.info(
            "Chat report filed",
            extra={"case": case_reference(case_id), "report_id": report.pk},
        )


class StatementOfReasonsService:
    """Record a decision against a person and tell them why (DSA Art. 17).

    The one way a statement goes out, whoever decided: staff closing a
    report, staff acting on their own, and later a room's organizers.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        cases: ModerationCaseRepositoryProtocol,
        statements: StatementOfReasonsRepositoryProtocol,
        mailer: ModerationMailerProtocol,
    ) -> None:
        self._transaction = transaction
        self._cases = cases
        self._statements = statements
        self._mailer = mailer

    def issue(self, statement: StatementOfReasons) -> IssuedStatement | None:
        """Record and mail a statement; None when its case already holds one.

        Raises:
            InvalidVerdictError: no action was taken, or a term Art. 17(3)
                needs is missing.
        """
        if statement.decision == ModerationDecision.NO_ACTION:
            msg = "A statement of reasons explains an action taken."
            raise InvalidVerdictError(msg)
        _check_terms(
            decision=statement.decision,
            ground=statement.ground,
            legal_provision=statement.legal_provision,
            suspended_until=statement.suspended_until,
        )
        with self._transaction.atomic():
            if statement.case_id is not None and self._statements.exists(
                case_id=statement.case_id, user_id=statement.user_id
            ):
                return None
            case_id = (
                statement.case_id
                if statement.case_id is not None
                else self._cases.open()
            )
            self._statements.create(
                {
                    "case_id": case_id,
                    "user_id": statement.user_id,
                    "decision": statement.decision,
                    "ground": statement.ground,
                    "legal_provision": statement.legal_provision.strip(),
                    "suspended_until": statement.suspended_until,
                    "facts": statement.facts.strip(),
                    "from_report": statement.from_report,
                    "automated": statement.automated,
                }
            )
            mailed = self._mailer.send_statement(statement=statement, case_id=case_id)
        logger.info(
            "Statement of reasons issued",
            extra={
                "case": case_reference(case_id),
                "user_id": statement.user_id,
                "decision": statement.decision.value,
                "ground": statement.ground.value,
                "from_report": statement.from_report,
                "automated": statement.automated,
                "mailed": mailed,
            },
        )
        return IssuedStatement(
            case_id=case_id, user_id=statement.user_id, mailed=mailed
        )


def _check_terms(
    *,
    decision: ModerationDecision,
    ground: ModerationGround | None,
    legal_provision: str,
    suspended_until: date | None,
) -> None:
    if ground == ModerationGround.ILLEGAL_CONTENT and not legal_provision.strip():
        msg = "Name the provision of law the content breaks."
        raise InvalidVerdictError(msg)
    if decision == ModerationDecision.ACCOUNT_SUSPENDED and suspended_until is None:
        msg = "Say until when the account is suspended."
        raise InvalidVerdictError(msg)


def _decision_record(verdict: ModerationVerdict) -> ModerationDecisionDict:
    if verdict.status == ModerationStatus.OPEN:
        msg = "A decision closes the report as actioned or rejected."
        raise InvalidVerdictError(msg)
    if verdict.status == ModerationStatus.ACTIONED and (
        verdict.decision == ModerationDecision.NO_ACTION or verdict.ground is None
    ):
        msg = "An actioned report names the action taken and its ground."
        raise InvalidVerdictError(msg)
    if not verdict.decision_text.strip():
        msg = "Explain the decision; the reporter and the person affected read it."
        raise InvalidVerdictError(msg)
    if not (rejected := verdict.status == ModerationStatus.REJECTED):
        _check_terms(
            decision=verdict.decision,
            ground=verdict.ground,
            legal_provision=verdict.legal_provision,
            suspended_until=verdict.suspended_until,
        )
    return {
        "status": verdict.status,
        "decision": ModerationDecision.NO_ACTION if rejected else verdict.decision,
        "ground": "" if rejected or verdict.ground is None else verdict.ground.value,
        "legal_provision": "" if rejected else verdict.legal_provision.strip(),
        "suspended_until": None if rejected else verdict.suspended_until,
        "decision_text": verdict.decision_text.strip(),
        "resolved_at": datetime.now(tz=UTC),
    }


class ModerationDecisionService:
    """Close reports, tell their reporters, and explain any action taken."""

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        cases: ModerationCaseRepositoryProtocol,
        notices: ContentNoticeRepositoryProtocol,
        reports: ChatReportRepositoryProtocol,
        statements: StatementOfReasonsServiceProtocol,
        mailer: ModerationMailerProtocol,
    ) -> None:
        self._transaction = transaction
        self._cases = cases
        self._notices = notices
        self._reports = reports
        self._statements = statements
        self._mailer = mailer

    @staticmethod
    def check(verdict: ModerationVerdict) -> None:
        """Refuse a verdict before anything acts on it.

        Raises:
            InvalidVerdictError: the verdict does not hold together.
        """
        _decision_record(verdict)

    def decide_notices(
        self,
        *,
        notice_ids: list[int],
        verdict: ModerationVerdict,
        affected_user_id: int | None,
    ) -> ModerationDecisionsDTO:
        """Close notices with one verdict.

        Raises:
            InvalidVerdictError: the verdict does not hold together, or one
                affected account is named for several notices.
        """
        record = _decision_record(verdict)
        if affected_user_id is not None and len(notice_ids) > 1:
            msg = "Name an affected account only when deciding a single notice."
            raise InvalidVerdictError(msg)
        decided, statements = 0, []
        with self._transaction.atomic():
            for pk in notice_ids:
                notice = self._notices.read(pk)
                if not self._notices.decide(pk, record):
                    continue
                decided += 1
                case_id = self._case_of(notice.case_id)
                if notice.reporter_email:
                    self._mailer.send_outcome(
                        ReporterOutcome(
                            case_id=case_id,
                            status=record["status"],
                            decision_text=record["decision_text"],
                            address=notice.reporter_email,
                            language=notice.language,
                        )
                    )
                if affected_user_id is not None and (
                    issued := self._explain(
                        record,
                        verdict=verdict,
                        user_id=affected_user_id,
                        case_id=case_id,
                    )
                ):
                    statements.append(issued)
        logger.info(
            "Content notices decided",
            extra={"status": record["status"].value, "count": decided},
        )
        return ModerationDecisionsDTO(decided=decided, statements=statements)

    def decide_chat_reports(
        self, *, report_ids: list[int], verdict: ModerationVerdict
    ) -> ModerationDecisionsDTO:
        """Close chat reports with one verdict.

        Raises:
            InvalidVerdictError: the verdict does not hold together.
        """
        record = _decision_record(verdict)
        decided, statements = 0, []
        # A message's reports filed before cases were shared may sit under
        # several cases; its author still hears about it once.
        explained: set[tuple[int, str, int]] = set()
        with self._transaction.atomic():
            for pk in report_ids:
                report = self._reports.read(pk)
                if not self._reports.decide(pk, record):
                    continue
                decided += 1
                case_id = self._case_of(report.case_id)
                self._mailer.send_outcome(
                    ReporterOutcome(
                        case_id=case_id,
                        status=record["status"],
                        decision_text=record["decision_text"],
                        reporter_id=report.reporter_id,
                    )
                )
                if report.reported_user_id is None:
                    continue
                key = (report.reported_user_id, report.room_id, report.message_id)
                if key in explained:
                    continue
                explained.add(key)
                if issued := self._explain(
                    record,
                    verdict=verdict,
                    user_id=report.reported_user_id,
                    case_id=case_id,
                ):
                    statements.append(issued)
        logger.info(
            "Chat reports decided",
            extra={"status": record["status"].value, "count": decided},
        )
        return ModerationDecisionsDTO(decided=decided, statements=statements)

    def _case_of(self, case_id: int | None) -> int:
        return case_id if case_id is not None else self._cases.open()

    def _explain(
        self,
        record: ModerationDecisionDict,
        *,
        verdict: ModerationVerdict,
        user_id: int,
        case_id: int,
    ) -> IssuedStatement | None:
        if record["status"] != ModerationStatus.ACTIONED or verdict.ground is None:
            return None
        return self._statements.issue(
            StatementOfReasons(
                user_id=user_id,
                case_id=case_id,
                decision=record["decision"],
                ground=verdict.ground,
                legal_provision=record["legal_provision"],
                suspended_until=record["suspended_until"],
                facts=record["decision_text"],
                from_report=True,
            )
        )


def _month_start(moment: datetime, *, back: int) -> datetime:
    index = moment.year * 12 + moment.month - 1 - back
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC)


class ActiveRecipientsService:
    """Average monthly active accounts, for UKE on request (DSA Art. 24(3))."""

    def __init__(self, *, repository: ActiveRecipientsRepositoryProtocol) -> None:
        self._repository = repository

    def monthly_average(self, *, now: datetime) -> MonthlyActiveRecipientsDTO:
        starts = [
            _month_start(now, back=back)
            for back in range(ACTIVE_RECIPIENT_MONTHS, -1, -1)
        ]
        months = [
            (start, self._repository.count_active_accounts(start=start, end=end))
            for start, end in pairwise(starts)
        ]
        return MonthlyActiveRecipientsDTO(
            months=months, average=sum(count for __, count in months) / len(months)
        )
