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
    CaseStatus,
    ModerationDecision,
    ModerationStatus,
    ModerationVerdict,
    case_reference,
)
from ludamus.pacts.staff_cases import (
    CASE_TITLE_MAX_LENGTH,
    STAFF_REPLY_MAX_LENGTH,
    CaseDetailDTO,
    CaseEmailDirection,
    CaseOpenedPost,
    DecisionPost,
    EmailInPost,
    EmailOutPost,
    NotePost,
    StaffCaseError,
    StaffCaseErrorCode,
    StaffEmailOutcome,
    StaffEmailReceipt,
    StaffThreadEntry,
)
from ludamus.specs.moderation import URGENT_NOTICE_CATEGORIES
from ludamus.specs.staff_cases import STAFF_CASE_SUBJECT_REFERENCE

if TYPE_CHECKING:
    from ludamus.pacts.moderation import ModerationDecisionServiceProtocol
    from ludamus.pacts.parley import (
        ParleyMembershipOutboxProtocol,
        ParleyServiceProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.staff_cases import (
        CaseDTO,
        InboundEmail,
        InboxCaseDTO,
        StaffCaseMailerProtocol,
        StaffCaseRepositoryProtocol,
        StaffDecision,
        StaffMemberDTO,
        StaffThreadMessage,
        StaffThreadProtocol,
    )

logger = logging.getLogger(__name__)
_OPEN = ModerationStatus.OPEN


def subject_reference(subject: str) -> int | None:
    """Find the case number a subject names in "[Z-1234]", if any."""
    match = STAFF_CASE_SUBJECT_REFERENCE.search(subject)
    return None if match is None else int(match.group(1))


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


def _open_records(case: CaseDTO) -> tuple[list[int], list[int]]:
    return (
        [notice.pk for notice in case.notices if notice.status == _OPEN],
        [report.pk for report in case.chat_reports if report.status == _OPEN],
    )


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

    def staff(self, *, actor_id: int) -> list[StaffMemberDTO]:
        self._require_staff(actor_id)
        return self._repository.list_staff()

    def counts(self, *, actor_id: int) -> dict[CaseStatus, int]:
        self._require_staff(actor_id)
        return self._repository.count_by_status()

    def cases(
        self, *, actor_id: int, status: CaseStatus, limit: int, offset: int
    ) -> list[InboxCaseDTO]:
        """List one state's cases, child safety first, then newest."""
        self._require_staff(actor_id)
        return self._repository.list_cases(
            status, urgent=URGENT_NOTICE_CATEGORIES, limit=limit, offset=offset
        )

    def read(self, *, actor_id: int, case_id: int) -> CaseDetailDTO:
        """Show a case, giving it its thread the first time anyone looks."""
        self._require_staff(actor_id)
        case = self._case(case_id)
        if case.thread_id is None:
            with self._transaction.atomic():
                self._thread_of(case)
            case = self._case(case_id)
        notices, reports = _open_records(case)
        return CaseDetailDTO(
            case=case,
            emails=self._repository.list_emails(case_id),
            staff=self._repository.list_staff(),
            decidable=bool(notices or reports),
        )

    def sync_threads(self) -> None:
        """Bring every case's thread in step with who is staff now."""
        with self._transaction.atomic():
            self._sync(None)

    def receive_email(self, email: InboundEmail) -> StaffEmailReceipt:
        """File mail to the staff address with its case, or open one for it."""
        if (seen := self._repository.email_seen(email.message_id)) is not None:
            logger.info("staff email already filed: case=%s", case_reference(seen))
            return StaffEmailReceipt(outcome=StaffEmailOutcome.DUPLICATE, case_id=seen)
        with self._transaction.atomic():
            case_id = self._named_case(email.subject)
            outcome = (
                StaffEmailOutcome.OPENED
                if case_id is None
                else StaffEmailOutcome.ATTACHED
            )
            if case_id is None:
                case_id = self._repository.open_for_email(
                    {
                        "title": email.subject[:CASE_TITLE_MAX_LENGTH],
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
            case = self._case(case_id)
            self._post(
                case,
                EmailInPost(
                    sender=email.from_name or email.from_address,
                    subject=email.subject,
                    body=email.body,
                    attachments=len(email.attachments),
                ),
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
            raise StaffCaseError(StaffCaseErrorCode.INVALID_BODY)
        case = self._case(case_id)
        if not by_email:
            with self._transaction.atomic():
                self._post(case, NotePost(staff=staff, body=body))
            return
        if not case.reply_to:
            raise StaffCaseError(StaffCaseErrorCode.NO_RECIPIENT)
        nonce = uuid4().hex
        subject = f"[{case.reference}] {case.title}".strip()
        with self._transaction.atomic():
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
                case,
                EmailOutPost(staff=staff, address=case.reply_to, body=body),
                nonce=f"reply-{nonce}",
            )
        logger.info("staff case answered by email: case=%s", case.reference)

    def assign(self, *, actor_id: int, case_id: int, assignee_id: int | None) -> None:
        self._require_staff(actor_id)
        if assignee_id is not None and self._repository.read_staff(assignee_id) is None:
            raise StaffCaseError(StaffCaseErrorCode.INVALID_ASSIGNEE)
        case = self._case(case_id)
        self._repository.set_assignee(case_id=case.pk, assignee_id=assignee_id)

    def close(self, *, actor_id: int, case_id: int) -> None:
        """Close a case with nothing left to decide, such as a question answered."""
        self._require_staff(actor_id)
        case = self._case(case_id)
        if any(_open_records(case)):
            raise StaffCaseError(StaffCaseErrorCode.UNDECIDED)
        self._repository.set_status(case_id=case.pk, status=CaseStatus.CLOSED)

    def preview(self, decision: StaffDecision) -> str:
        """Word the statement of reasons the person affected would get."""
        return self._mailer.verdict_text(verdict_of(decision))

    def decide(self, *, actor_id: int, case_id: int, decision: StaffDecision) -> None:
        """Close the case's open notices and chat reports, as the admin does.

        Raises:
            StaffCaseError: nothing is open to decide, the named account is
                unknown, or the chat could not remove every message.
            InvalidVerdictError: the decision does not hold together.
        """
        staff = self._require_staff(actor_id)
        verdict = verdict_of(decision)
        self._decisions.check(verdict)
        case = self._case(case_id)
        notices, reports = _open_records(case)
        if not (notices or reports):
            raise StaffCaseError(StaffCaseErrorCode.NOTHING_TO_DECIDE)
        affected = self._affected(decision.affected_account, notices=notices)
        if reports and verdict.decision == ModerationDecision.CONTENT_REMOVED:
            # NOTE: deleted before the decision commits; a miss leaves it open.
            removal = self._chat.delete_reported(
                report_ids=reports, now=datetime.now(UTC)
            )
            if removal.failed:
                raise StaffCaseError(StaffCaseErrorCode.CHAT_UNAVAILABLE)
        with self._transaction.atomic():
            if reports:
                self._decisions.decide_chat_reports(report_ids=reports, verdict=verdict)
            if notices:
                self._decisions.decide_notices(
                    notice_ids=notices, verdict=verdict, affected_user_id=affected
                )
            self._repository.set_decided_by(case_id=case.pk, user_id=staff.pk)
            self._repository.set_status(case_id=case.pk, status=CaseStatus.CLOSED)
            self._post(
                case,
                DecisionPost(
                    staff=staff,
                    status=verdict.status,
                    decision_text=verdict.decision_text,
                ),
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
            raise StaffCaseError(StaffCaseErrorCode.NO_NOTICE)
        if (user_id := self._repository.find_account(identifier)) is None:
            raise StaffCaseError(StaffCaseErrorCode.UNKNOWN_ACCOUNT)
        return user_id

    def _require_staff(self, user_id: int) -> StaffMemberDTO:
        if (staff := self._repository.read_staff(user_id)) is None:
            raise NotFoundError
        return staff

    def _case(self, case_id: int) -> CaseDTO:
        return self._repository.read(case_id, urgent=URGENT_NOTICE_CATEGORIES)

    def _named_case(self, subject: str) -> int | None:
        if (number := subject_reference(subject)) is None:
            return None
        try:
            return self._case(number).pk
        except NotFoundError:
            return None

    def _thread_of(self, case: CaseDTO) -> int:
        """Give the case its thread, the first time anyone needs it."""
        if case.thread_id is not None:
            return case.thread_id
        thread_id = self._repository.open_thread(case.pk)
        self._sync([thread_id])
        self._thread.post(
            StaffThreadEntry(
                thread_id=thread_id,
                reference=case.reference,
                message=CaseOpenedPost(kind=case.kind, title=case.title),
                nonce=f"opened-{case.pk}",
            )
        )
        return thread_id

    def _sync(self, thread_ids: list[int] | None) -> None:
        staff = [member.pk for member in self._repository.list_staff()]
        changed = self._repository.set_thread_members(
            user_ids=staff, thread_ids=thread_ids
        )
        self._memberships.schedule(conversation_ids=changed)

    def _post(
        self, case: CaseDTO, message: StaffThreadMessage, *, nonce: str = ""
    ) -> None:
        self._thread.post(
            StaffThreadEntry(
                thread_id=self._thread_of(case),
                reference=case.reference,
                message=message,
                nonce=nonce or uuid4().hex,
            )
        )
