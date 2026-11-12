"""Staff cases: reports, notices, decisions and appeals, one place for each.

Only staff (`is_staff`) see or change a case. Its thread is a staff-only
Parley conversation whose members follow who is staff. Mail to the staff
address lands in the case its subject names ("[Z-1234]") or opens a new
one; a reply sent by email goes back with that reference in its subject, so
the answer finds the same case. A reply on a decided case is an appeal, and
whoever made the decision cannot decide it again.
"""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.staff_cases import (
    STAFF_CASE_TITLE_MAX_LENGTH,
    STAFF_REPLY_MAX_LENGTH,
    STAFF_THREAD_POST_MAX_LENGTH,
    StaffCaseDetailDTO,
    StaffCaseError,
    StaffCaseKind,
    StaffCaseStatus,
    StaffEmailDirection,
    StaffEmailOutcome,
    StaffEmailReceipt,
    StaffInboxDTO,
    StaffThreadEntry,
    StaffThreadEvent,
)
from ludamus.specs.staff_cases import (
    STAFF_CASE_RETENTION,
    STAFF_CASE_SUBJECT_REFERENCE,
    STAFF_EMAIL_SUBJECT_FALLBACK,
)

if TYPE_CHECKING:
    from ludamus.pacts.parley import ParleyMembershipOutboxProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.staff_cases import (
        InboundEmail,
        ModerationAction,
        ModerationGround,
        StaffCaseDecisionDTO,
        StaffCaseDTO,
        StaffCaseListItemDTO,
        StaffCaseRepositoryProtocol,
        StaffMailerProtocol,
        StaffMemberDTO,
        StaffThreadProtocol,
    )

logger = logging.getLogger(__name__)


def subject_reference(subject: str) -> int | None:
    """Find the case number a subject names in "[Z-1234]", if any."""
    match = STAFF_CASE_SUBJECT_REFERENCE.search(subject)
    return None if match is None else int(match.group(1))


def reply_subject(case: StaffCaseDTO) -> str:
    title = case.title or STAFF_EMAIL_SUBJECT_FALLBACK
    return f"[{case.reference}] {title}"


def may_decide(case: StaffCaseDTO, actor_id: int) -> bool:
    """Anyone on staff decides first; an appeal goes to someone else."""
    return case.decision is None or case.decision.decided_by_id != actor_id


def inbox_order(case: StaffCaseListItemDTO) -> tuple[bool, float]:
    return (not case.child_safety, -case.created_at.timestamp())


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
        mailer: StaffMailerProtocol,
        memberships: ParleyMembershipOutboxProtocol,
    ) -> None:
        self._transaction = transaction
        self._repository = repository
        self._thread = thread
        self._mailer = mailer
        self._memberships = memberships

    def inbox(self, *, actor_id: int, status: StaffCaseStatus) -> StaffInboxDTO:
        """List the cases in one state, child safety first, and count each state.

        Brings every case's thread in step with who is staff now: being made
        staff, or no longer, happens in the admin, which tells nobody.
        """
        self._require_staff(actor_id)
        with self._transaction.atomic():
            self._sync_threads(None)
        return StaffInboxDTO(
            status=status,
            cases=sorted(self._repository.list_cases(status), key=inbox_order),
            counts=self._repository.count_by_status(),
        )

    def read(self, *, actor_id: int, case_id: int) -> StaffCaseDetailDTO:
        self._require_staff(actor_id)
        case = self._repository.read(case_id)
        return StaffCaseDetailDTO(
            case=case,
            content=(
                None
                if case.report_id is None
                else self._repository.read_content(case.report_id)
            ),
            emails=self._repository.list_emails(case_id),
            staff=self._repository.list_staff(),
            may_decide=may_decide(case, actor_id),
        )

    def open_for_chat_report(
        self, *, reporter_id: int, room_id: str, message_id: int
    ) -> StaffCaseDTO | None:
        """Open the case of a chat report just kept; the one it has, if any."""
        facts = self._repository.find_chat_report(
            reporter_id=reporter_id, room_id=room_id, message_id=message_id
        )
        if facts is None:
            return None
        if (existing := self._repository.read_for_report(facts.report_id)) is not None:
            return existing
        with self._transaction.atomic():
            case = self._open(
                kind=StaffCaseKind.CHAT_REPORT,
                title=facts.reason,
                child_safety=facts.involves_minor,
                external_email=facts.reporter_email,
                external_name=facts.reporter_name,
                report_id=facts.report_id,
            )
            self._post(
                case=case,
                event=StaffThreadEvent.CASE_OPENED,
                author=None,
                body=facts.reason,
                details={"kind": case.kind, "room": facts.room_id},
            )
        logger.info(
            "staff case opened: case=%s kind=%s report=%s child_safety=%s",
            case.reference,
            case.kind,
            facts.report_id,
            case.child_safety,
        )
        return case

    def receive_email(self, email: InboundEmail) -> StaffEmailReceipt:
        """File mail to the staff address with its case, or open one for it."""
        if (seen := self._repository.email_seen(email.message_id)) is not None:
            logger.info("staff email already filed: case=%s", seen)
            return StaffEmailReceipt(outcome=StaffEmailOutcome.DUPLICATE, case_id=seen)
        with self._transaction.atomic():
            if (case := self._named_case(email.subject)) is None:
                outcome = StaffEmailOutcome.OPENED
                case = self._open(
                    kind=StaffCaseKind.EMAIL,
                    title=email.subject,
                    child_safety=False,
                    external_email=email.from_address,
                    external_name=email.from_name,
                    report_id=None,
                )
            else:
                outcome = StaffEmailOutcome.ATTACHED
                if case.status != StaffCaseStatus.OPEN:
                    self._repository.set_status(
                        case_id=case.pk, status=StaffCaseStatus.OPEN
                    )
            self._repository.add_email(
                {
                    "case_id": case.pk,
                    "direction": StaffEmailDirection.IN,
                    "message_id": email.message_id,
                    "address": email.from_address,
                    "name": email.from_name,
                    "subject": email.subject,
                    "body": email.body,
                    "attachments": email.attachments,
                    "sent_by_id": None,
                }
            )
            self._post(
                case=case,
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
        return StaffEmailReceipt(outcome=outcome, case_id=case.pk)

    def reply(self, *, actor_id: int, case_id: int, body: str, by_email: bool) -> None:
        """Write into the case: a note for staff, or an answer mailed out too."""
        staff = self._require_staff(actor_id)
        body = body.strip()
        if not body or len(body) > STAFF_REPLY_MAX_LENGTH:
            raise StaffCaseError("invalid_body")
        case = self._repository.read(case_id)
        if not by_email:
            with self._transaction.atomic():
                self._post(
                    case=case, event=StaffThreadEvent.NOTE, author=staff, body=body
                )
            return
        if not case.external_email:
            raise StaffCaseError("no_recipient")
        nonce = uuid4().hex
        subject = reply_subject(case)
        with self._transaction.atomic():
            self._repository.add_email(
                {
                    "case_id": case.pk,
                    "direction": StaffEmailDirection.OUT,
                    "message_id": nonce,
                    "address": case.external_email,
                    "name": case.external_name,
                    "subject": subject,
                    "body": body,
                    "attachments": [],
                    "sent_by_id": staff.pk,
                }
            )
            self._repository.set_status(case_id=case.pk, status=StaffCaseStatus.WAITING)
            self._mailer.send(
                to=case.external_email, subject=subject, body=body, nonce=nonce
            )
            self._post(
                case=case,
                event=StaffThreadEvent.EMAIL_OUT,
                author=staff,
                body=body,
                details={"address": case.external_email},
                nonce=f"reply-{nonce}",
            )
        logger.info("staff case answered by email: case=%s", case.reference)

    def assign(self, *, actor_id: int, case_id: int, assignee_id: int | None) -> None:
        self._require_staff(actor_id)
        if assignee_id is not None and self._repository.read_staff(assignee_id) is None:
            raise StaffCaseError("invalid_assignee")
        case = self._repository.read(case_id)
        self._repository.set_assignee(case_id=case.pk, assignee_id=assignee_id)

    def decide(
        self,
        *,
        actor_id: int,
        case_id: int,
        action: ModerationAction,
        ground: ModerationGround,
    ) -> StaffCaseDecisionDTO:
        staff = self._require_staff(actor_id)
        case = self._repository.read(case_id)
        if not may_decide(case, actor_id):
            raise StaffCaseError("same_decider")
        with self._transaction.atomic():
            decision = self._repository.record_decision(
                {
                    "case_id": case.pk,
                    "action": action,
                    "ground": ground,
                    "decided_by_id": staff.pk,
                }
            )
            self._repository.set_status(case_id=case.pk, status=StaffCaseStatus.CLOSED)
            # TODO(feat/dsa-minimum): apply it, send reasons and outcome there.
            self._post(
                case=case,
                event=StaffThreadEvent.DECISION,
                author=staff,
                body="",
                details={"action": action, "ground": ground},
            )
        logger.info(
            "staff case decided: case=%s action=%s ground=%s appeal=%s",
            case.reference,
            action,
            ground,
            case.decision is not None,
        )
        return decision

    def _require_staff(self, user_id: int) -> StaffMemberDTO:
        if (staff := self._repository.read_staff(user_id)) is None:
            raise NotFoundError
        return staff

    def _named_case(self, subject: str) -> StaffCaseDTO | None:
        if (number := subject_reference(subject)) is None:
            return None
        try:
            return self._repository.read(number)
        except NotFoundError:
            return None

    def _open(
        self,
        *,
        kind: StaffCaseKind,
        title: str,
        child_safety: bool,
        external_email: str,
        external_name: str,
        report_id: int | None,
    ) -> StaffCaseDTO:
        title = _clip(" ".join(title.split()), STAFF_CASE_TITLE_MAX_LENGTH)
        conversation_id = self._repository.create_thread(title)
        case = self._repository.create(
            {
                "kind": kind,
                "title": title,
                "child_safety": child_safety,
                "conversation_id": conversation_id,
                "external_email": external_email,
                "external_name": external_name,
                "report_id": report_id,
            }
        )
        self._sync_threads([conversation_id])
        return case

    def _sync_threads(self, conversation_ids: list[int] | None) -> None:
        staff = [member.pk for member in self._repository.list_staff()]
        changed = self._repository.set_thread_members(
            user_ids=staff, conversation_ids=conversation_ids
        )
        self._memberships.schedule(conversation_ids=changed)

    def _post(
        self,
        *,
        case: StaffCaseDTO,
        event: StaffThreadEvent,
        author: StaffMemberDTO | None,
        body: str,
        author_name: str = "",
        details: dict[str, str] | None = None,
        nonce: str | None = None,
    ) -> None:
        self._thread.post(
            StaffThreadEntry(
                conversation_id=case.conversation_id,
                event=event,
                author_id=None if author is None else author.pk,
                author_name=author_name if author is None else author.name,
                body=_clip(body, STAFF_THREAD_POST_MAX_LENGTH),
                details={"reference": case.reference, **(details or {})},
                nonce=nonce or uuid4().hex,
                retain_for=STAFF_CASE_RETENTION,
            )
        )
