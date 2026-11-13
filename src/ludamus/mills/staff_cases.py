"""The staff inbox over moderation cases.

Only staff (`is_staff`) see or change a case. Notices and chat reports open
their cases on arrival; mail to the staff address files itself under the
case its subject names ("[Z-1234]", as every mail about a case carries) or
opens a new one. A case's thread is a staff-only Parley conversation, opened
the first time someone needs it, whose members follow who is staff.

Deciding in the inbox closes the case's open records exactly as the admin
does: chat messages removed through the chat, reporters told the outcome,
the person affected sent a statement of reasons.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.moderation import (
    ModerationDecision,
    ModerationStatus,
    ModerationVerdict,
    StatementOfReasons,
    case_reference,
)
from ludamus.pacts.staff_cases import (
    CASE_TITLE_MAX_LENGTH,
    STAFF_REPLY_MAX_LENGTH,
    STAFF_THREAD_POST_MAX_LENGTH,
    CaseDetailDTO,
    CaseEmailDirection,
    CaseKind,
    CaseStatus,
    InboxCaseDTO,
    StaffCaseError,
    StaffEmailOutcome,
    StaffEmailReceipt,
    StaffInboxDTO,
    StaffThreadEntry,
    StaffThreadEvent,
)
from ludamus.specs.moderation import URGENT_NOTICE_CATEGORIES
from ludamus.specs.staff_cases import (
    STAFF_CASE_RETENTION,
    STAFF_CASE_SUBJECT_REFERENCE,
    STAFF_EMAIL_SUBJECT_FALLBACK,
)

if TYPE_CHECKING:
    from ludamus.pacts.moderation import (
        ModerationDecisionServiceProtocol,
        NoticeCategory,
    )
    from ludamus.pacts.parley import (
        ParleyMembershipOutboxProtocol,
        ParleyServiceProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.staff_cases import (
        CaseDTO,
        CaseRowDTO,
        InboundEmail,
        StaffCaseMailerProtocol,
        StaffCaseRepositoryProtocol,
        StaffDecision,
        StaffMemberDTO,
        StaffThreadProtocol,
    )

logger = logging.getLogger(__name__)


def subject_reference(subject: str) -> int | None:
    """Find the case number a subject names in "[Z-1234]", if any."""
    match = STAFF_CASE_SUBJECT_REFERENCE.search(subject)
    return None if match is None else int(match.group(1))


def reply_subject(case: CaseDTO) -> str:
    return f"[{case.reference}] {case.title or STAFF_EMAIL_SUBJECT_FALLBACK}"


def case_kind(
    *, has_notices: bool, has_chat_reports: bool, opened_by_email: bool
) -> CaseKind:
    if has_notices:
        return CaseKind.NOTICE
    if has_chat_reports:
        return CaseKind.CHAT_REPORT
    return CaseKind.EMAIL if opened_by_email else CaseKind.STATEMENT


def child_safety(*, categories: list[NoticeCategory], involves_minor: bool) -> bool:
    return involves_minor or any(c in URGENT_NOTICE_CATEGORIES for c in categories)


def verdict_of(decision: StaffDecision) -> ModerationVerdict:
    """Read "no action" as rejecting the reports; anything else acts on them."""
    rejected = decision.decision == ModerationDecision.NO_ACTION
    return ModerationVerdict(
        status=ModerationStatus.REJECTED if rejected else ModerationStatus.ACTIONED,
        decision=decision.decision,
        ground=None if rejected else decision.ground,
        decision_text=decision.decision_text,
        legal_provision=decision.legal_provision,
        suspended_until=decision.suspended_until,
    )


def _row(case: CaseRowDTO) -> InboxCaseDTO:
    return InboxCaseDTO(
        pk=case.pk,
        kind=case_kind(
            has_notices=case.has_notices,
            has_chat_reports=case.has_chat_reports,
            opened_by_email=case.opened_by_email,
        ),
        status=case.status,
        title=case.title,
        child_safety=child_safety(
            categories=case.notice_categories, involves_minor=case.involves_minor
        ),
        assignee_name=case.assignee_name,
        created_at=case.created_at,
    )


def _inbox_order(case: InboxCaseDTO) -> tuple[bool, float]:
    return (not case.child_safety, -case.created_at.timestamp())


def _kind(case: CaseDTO) -> CaseKind:
    return case_kind(
        has_notices=bool(case.notices),
        has_chat_reports=bool(case.chat_reports),
        opened_by_email=case.opened_by_email,
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _email_nonce(message_id: str) -> str:
    return f"email-{sha256(message_id.encode()).hexdigest()[:40]}"


class StaffCaseService:
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repository: StaffCaseRepositoryProtocol,
        thread: StaffThreadProtocol,
        mailer: StaffCaseMailerProtocol,
        memberships: ParleyMembershipOutboxProtocol,
        decisions: ModerationDecisionServiceProtocol,
        chat: ParleyServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._repository = repository
        self._thread = thread
        self._mailer = mailer
        self._memberships = memberships
        self._decisions = decisions
        self._chat = chat

    def inbox(self, *, actor_id: int, status: CaseStatus) -> StaffInboxDTO:
        """List the cases in one state, child safety first, and count each state.

        Brings every case's thread in step with who is staff now: being made
        staff, or no longer, happens in the admin, which tells nobody.
        """
        self._require_staff(actor_id)
        with self._transaction.atomic():
            self._sync_threads(None)
        cases = [_row(case) for case in self._repository.list_cases(status)]
        return StaffInboxDTO(
            status=status,
            cases=sorted(cases, key=_inbox_order),
            counts=self._repository.count_by_status(),
        )

    def read(self, *, actor_id: int, case_id: int) -> CaseDetailDTO:
        self._require_staff(actor_id)
        case = self._repository.read(case_id)
        if case.thread_id is None:
            with self._transaction.atomic():
                self._with_thread(case)
            case = self._repository.read(case_id)
        notices, reports = self._open_records(case)
        return CaseDetailDTO(
            case=case,
            kind=_kind(case),
            child_safety=child_safety(
                categories=[notice.category for notice in case.notices],
                involves_minor=any(r.involves_minor for r in case.chat_reports),
            ),
            emails=self._repository.list_emails(case_id),
            staff=self._repository.list_staff(),
            decidable=bool(notices or reports),
        )

    def receive_email(self, email: InboundEmail) -> StaffEmailReceipt:
        """File mail to the staff address with its case, or open one for it."""
        if (seen := self._repository.email_seen(email.message_id)) is not None:
            logger.info("staff email already filed: case=%s", case_reference(seen))
            return StaffEmailReceipt(outcome=StaffEmailOutcome.DUPLICATE, case_id=seen)
        with self._transaction.atomic():
            case_id = self._named_case(email.subject)
            outcome = (
                StaffEmailOutcome.ATTACHED
                if case_id is not None
                else StaffEmailOutcome.OPENED
            )
            if case_id is None:
                case_id = self._repository.open_for_email(
                    {
                        "title": _clip(
                            " ".join(email.subject.split()), CASE_TITLE_MAX_LENGTH
                        ),
                        "external_email": email.from_address,
                        "external_name": email.from_name,
                    }
                )
            self._repository.set_status(case_id=case_id, status=CaseStatus.OPEN)
            self._repository.add_email(
                {
                    "case_id": case_id,
                    "direction": CaseEmailDirection.IN,
                    "message_id": email.message_id,
                    "address": email.from_address,
                    "name": email.from_name,
                    "subject": email.subject,
                    "body": email.body,
                    "attachments": email.attachments,
                    "sent_by_id": None,
                }
            )
            case = self._repository.read(case_id)
            self._post(
                thread_id=self._with_thread(case),
                reference=case.reference,
                event=StaffThreadEvent.EMAIL_IN,
                author=None,
                author_name=email.from_name or email.from_address,
                body=email.body,
                details={
                    "address": email.from_address,
                    "subject": email.subject,
                    "attachments": str(len(email.attachments)),
                },
                nonce=_email_nonce(email.message_id),
            )
        logger.info(
            "staff email filed: case=%s outcome=%s attachments=%s",
            case.reference,
            outcome,
            len(email.attachments),
        )
        return StaffEmailReceipt(outcome=outcome, case_id=case_id)

    def reply(self, *, actor_id: int, case_id: int, body: str, by_email: bool) -> None:
        """Write into the case: a note for staff, or an answer mailed out too."""
        staff = self._require_staff(actor_id)
        body = body.strip()
        if not body or len(body) > STAFF_REPLY_MAX_LENGTH:
            raise StaffCaseError("invalid_body")
        case = self._repository.read(case_id)
        if by_email and not case.reply_to:
            raise StaffCaseError("no_recipient")
        with self._transaction.atomic():
            thread_id = self._with_thread(case)
            if not by_email:
                self._post(
                    thread_id=thread_id,
                    reference=case.reference,
                    event=StaffThreadEvent.NOTE,
                    author=staff,
                    body=body,
                )
                return
            nonce = uuid4().hex
            subject = reply_subject(case)
            self._repository.add_email(
                {
                    "case_id": case.pk,
                    "direction": CaseEmailDirection.OUT,
                    "message_id": nonce,
                    "address": case.reply_to,
                    "name": case.reply_name,
                    "subject": subject,
                    "body": body,
                    "attachments": [],
                    "sent_by_id": staff.pk,
                }
            )
            self._repository.set_status(case_id=case.pk, status=CaseStatus.WAITING)
            self._mailer.send_reply(
                to=case.reply_to, subject=subject, body=body, nonce=nonce
            )
            self._post(
                thread_id=thread_id,
                reference=case.reference,
                event=StaffThreadEvent.EMAIL_OUT,
                author=staff,
                body=body,
                details={"address": case.reply_to},
                nonce=f"reply-{nonce}",
            )
        logger.info("staff case answered by email: case=%s", case.reference)

    def assign(self, *, actor_id: int, case_id: int, assignee_id: int | None) -> None:
        self._require_staff(actor_id)
        if assignee_id is not None and self._repository.read_staff(assignee_id) is None:
            raise StaffCaseError("invalid_assignee")
        case = self._repository.read(case_id)
        self._repository.set_assignee(case_id=case.pk, assignee_id=assignee_id)

    def close(self, *, actor_id: int, case_id: int) -> None:
        """Close a case with nothing left to decide, such as a question answered."""
        self._require_staff(actor_id)
        case = self._repository.read(case_id)
        if any(self._open_records(case)):
            raise StaffCaseError("undecided")
        self._repository.set_status(case_id=case.pk, status=CaseStatus.CLOSED)

    def preview(self, decision: StaffDecision) -> str:
        """Word the statement of reasons the person affected would get."""
        verdict = verdict_of(decision)
        if verdict.ground is None:
            return ""
        return self._mailer.statement_text(
            StatementOfReasons(
                user_id=0,
                case_id=None,
                decision=verdict.decision,
                ground=verdict.ground,
                facts=verdict.decision_text,
                from_report=True,
                legal_provision=verdict.legal_provision,
                suspended_until=verdict.suspended_until,
            )
        )

    def decide(self, *, actor_id: int, case_id: int, decision: StaffDecision) -> None:
        """Close the case's open notices and chat reports, as the admin does.

        Raises:
            StaffCaseError: nothing is open to decide, the named account is
                unknown, or the chat could not remove the message.
            InvalidVerdictError: the decision does not hold together.
        """
        staff = self._require_staff(actor_id)
        verdict = verdict_of(decision)
        self._decisions.check(verdict)
        case = self._repository.read(case_id)
        notices, reports = self._open_records(case)
        if not (notices or reports):
            raise StaffCaseError("nothing_to_decide")
        affected = self._affected(decision.affected_account, notices=notices)
        if reports and verdict.decision == ModerationDecision.CONTENT_REMOVED:
            removal = self._chat.delete_reported(
                report_ids=reports, now=datetime.now(UTC)
            )
            if not removal.deleted:
                raise StaffCaseError("chat_unavailable")
        with self._transaction.atomic():
            thread_id = self._with_thread(case)
            if reports:
                self._decisions.decide_chat_reports(report_ids=reports, verdict=verdict)
            if notices:
                self._decisions.decide_notices(
                    notice_ids=notices, verdict=verdict, affected_user_id=affected
                )
            self._repository.set_decided_by(case_id=case.pk, user_id=staff.pk)
            self._repository.set_status(case_id=case.pk, status=CaseStatus.CLOSED)
            self._post(
                thread_id=thread_id,
                reference=case.reference,
                event=StaffThreadEvent.DECISION,
                author=staff,
                body=verdict.decision_text,
                details={"status": verdict.status, "decision": verdict.decision},
            )
        logger.info(
            "staff case decided: case=%s status=%s decision=%s notices=%s reports=%s",
            case.reference,
            verdict.status,
            verdict.decision,
            len(notices),
            len(reports),
        )

    def _affected(self, identifier: str, *, notices: list[int]) -> int | None:
        if not (identifier := identifier.strip()):
            return None
        if not notices:
            raise StaffCaseError("no_notice")
        if (user_id := self._repository.find_account(identifier)) is None:
            raise StaffCaseError("unknown_account")
        return user_id

    @staticmethod
    def _open_records(case: CaseDTO) -> tuple[list[int], list[int]]:
        open_ = ModerationStatus.OPEN
        return (
            [notice.pk for notice in case.notices if notice.status == open_],
            [report.pk for report in case.chat_reports if report.status == open_],
        )

    def _require_staff(self, user_id: int) -> StaffMemberDTO:
        if (staff := self._repository.read_staff(user_id)) is None:
            raise NotFoundError
        return staff

    def _named_case(self, subject: str) -> int | None:
        if (number := subject_reference(subject)) is None:
            return None
        try:
            return self._repository.read(number).pk
        except NotFoundError:
            return None

    def _with_thread(self, case: CaseDTO) -> int:
        """Give the case its thread, the first time anyone needs it."""
        if case.thread_id is not None:
            return case.thread_id
        thread_id = self._repository.open_thread(case.pk)
        self._sync_threads([thread_id])
        self._post(
            thread_id=thread_id,
            reference=case.reference,
            event=StaffThreadEvent.CASE_OPENED,
            author=None,
            body=case.title,
            details={"kind": _kind(case), "opened": case.created_at.isoformat()},
            nonce=f"opened-{case.pk}",
        )
        return thread_id

    def _sync_threads(self, thread_ids: list[int] | None) -> None:
        staff = [member.pk for member in self._repository.list_staff()]
        changed = self._repository.set_thread_members(
            user_ids=staff, thread_ids=thread_ids
        )
        self._memberships.schedule(conversation_ids=changed)

    def _post(
        self,
        *,
        thread_id: int,
        reference: str,
        event: StaffThreadEvent,
        author: StaffMemberDTO | None,
        body: str,
        author_name: str = "",
        details: dict[str, str] | None = None,
        nonce: str | None = None,
    ) -> None:
        self._thread.post(
            StaffThreadEntry(
                thread_id=thread_id,
                event=event,
                author_id=None if author is None else author.pk,
                author_name=author_name if author is None else author.name,
                body=_clip(body, STAFF_THREAD_POST_MAX_LENGTH),
                details={"reference": reference, **(details or {})},
                nonce=nonce or uuid4().hex,
                retain_for=STAFF_CASE_RETENTION,
            )
        )
