from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count, Q

from ludamus.links.db.django.models import (
    ParleyConversation,
    ParleyConversationMember,
    ParleyReport,
    StaffCase,
    StaffCaseDecision,
    StaffCaseEmail,
    User,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.parley import ParleyConversationKind, ParleyMemberState
from ludamus.pacts.staff_cases import (
    ChatReportFacts,
    ModerationAction,
    ModerationGround,
    ReportedContentDTO,
    StaffCaseDecisionDTO,
    StaffCaseDTO,
    StaffCaseKind,
    StaffCaseListItemDTO,
    StaffCaseRepositoryProtocol,
    StaffCaseStatus,
    StaffEmailDirection,
    StaffMemberDTO,
)
from ludamus.pacts.staff_cases import StaffCaseEmailDTO as EmailDTO
from ludamus.pacts.user import AgeBand

if TYPE_CHECKING:
    from ludamus.pacts.staff_cases import (
        StaffCaseCreateDict,
        StaffCaseDecisionCreateDict,
        StaffCaseEmailCreateDict,
    )

_PRESENT = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)
_THREAD_TITLE_MAX_LENGTH = 80


def _staff() -> Q:
    return Q(is_staff=True, is_active=True)


def _name(user: User | None) -> str:
    return "" if user is None else user.get_full_name()


def _decision(decision: StaffCaseDecision) -> StaffCaseDecisionDTO:
    return StaffCaseDecisionDTO(
        action=ModerationAction(decision.action),
        ground=ModerationGround(decision.ground),
        decided_by_id=decision.decided_by_id,
        decided_by_name=_name(decision.decided_by),
        decided_at=decision.decided_at,
    )


def _case(case: StaffCase) -> StaffCaseDTO:
    return StaffCaseDTO(
        pk=case.pk,
        kind=StaffCaseKind(case.kind),
        status=StaffCaseStatus(case.status),
        title=case.title,
        child_safety=case.child_safety,
        assignee_id=case.assignee_id,
        conversation_id=case.conversation_id,
        external_email=case.external_email,
        external_name=case.external_name,
        report_id=case.report_id,
        notice_id=case.notice_id,
        decision=None if case.decision is None else _decision(case.decision),
        created_at=case.created_at,
    )


def _involves_minor(report: ParleyReport) -> bool:
    minors = Q(age_band=AgeBand.THIRTEEN_TO_FIFTEEN.value)
    people = [report.reporter_id, report.reported_user_id]
    if User.objects.filter(minors, pk__in=[pk for pk in people if pk]).exists():
        return True
    return (
        report.conversation_id is not None
        and ParleyConversationMember.objects.filter(
            conversation_id=report.conversation_id,
            state__in=_PRESENT,
            user__age_band=AgeBand.THIRTEEN_TO_FIFTEEN.value,
        ).exists()
    )


class StaffCaseRepository(StaffCaseRepositoryProtocol):
    @staticmethod
    def read_staff(user_id: int) -> StaffMemberDTO | None:
        user = User.objects.filter(_staff(), pk=user_id).first()
        return None if user is None else StaffMemberDTO(pk=user.pk, name=_name(user))

    @staticmethod
    def list_staff() -> list[StaffMemberDTO]:
        return [
            StaffMemberDTO(pk=user.pk, name=_name(user))
            for user in User.objects.filter(_staff()).order_by("name", "pk")
        ]

    @staticmethod
    def create_thread(title: str) -> int:
        return ParleyConversation.objects.create(
            kind=ParleyConversationKind.STAFF, title=title[:_THREAD_TITLE_MAX_LENGTH]
        ).pk

    @staticmethod
    def set_thread_members(
        *, user_ids: list[int], conversation_ids: list[int] | None
    ) -> list[int]:
        threads = ParleyConversation.objects.filter(kind=ParleyConversationKind.STAFF)
        if conversation_ids is not None:
            threads = threads.filter(pk__in=conversation_ids)
        thread_ids = list(threads.values_list("pk", flat=True))
        present: dict[int, set[int]] = {pk: set() for pk in thread_ids}
        for conversation_id, user_id in ParleyConversationMember.objects.filter(
            conversation_id__in=thread_ids, state__in=_PRESENT
        ).values_list("conversation_id", "user_id"):
            present[conversation_id].add(user_id)
        wanted = set(user_ids)
        changed = sorted(pk for pk, users in present.items() if users != wanted)
        ParleyConversationMember.objects.filter(
            conversation_id__in=changed, state__in=_PRESENT
        ).exclude(user_id__in=wanted).update(state=ParleyMemberState.LEFT)
        for conversation_id in changed:
            for user_id in wanted - present[conversation_id]:
                ParleyConversationMember.objects.update_or_create(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    defaults={"state": ParleyMemberState.ACTIVE, "is_admin": False},
                )
        return changed

    @staticmethod
    def create(data: StaffCaseCreateDict) -> StaffCaseDTO:
        return _case(StaffCase.objects.create(**data))

    @staticmethod
    def read(case_id: int) -> StaffCaseDTO:
        case = (
            StaffCase.objects.select_related("decision__decided_by")
            .filter(pk=case_id)
            .first()
        )
        if case is None:
            raise NotFoundError
        return _case(case)

    @staticmethod
    def read_for_report(report_id: int) -> StaffCaseDTO | None:
        case = (
            StaffCase.objects.select_related("decision__decided_by")
            .filter(report_id=report_id)
            .first()
        )
        return None if case is None else _case(case)

    @staticmethod
    def find_chat_report(
        *, reporter_id: int, room_id: str, message_id: int
    ) -> ChatReportFacts | None:
        report = (
            ParleyReport.objects.select_related("reporter")
            .filter(reporter_id=reporter_id, room_id=room_id, message_id=message_id)
            .first()
        )
        if report is None:
            return None
        return ChatReportFacts(
            report_id=report.pk,
            reason=report.reason,
            reporter_name=_name(report.reporter),
            reporter_email=report.reporter.email,
            room_id=report.room_id,
            involves_minor=_involves_minor(report),
        )

    @staticmethod
    def read_content(report_id: int) -> ReportedContentDTO:
        report = (
            ParleyReport.objects.select_related("reporter", "reported_user")
            .filter(pk=report_id)
            .first()
        )
        if report is None:
            raise NotFoundError
        author = report.reported_user
        return ReportedContentDTO(
            room_id=report.room_id,
            message_id=report.message_id,
            reason=report.reason,
            reporter_name=_name(report.reporter),
            author_id=report.reported_user_id,
            author_name=report.author_name or _name(author),
            author_age_band=None if author is None else AgeBand(author.age_band),
            author_joined_at=None if author is None else author.date_joined,
            body=report.body,
            written_at=report.written_at,
            deleted_at=report.deleted_at,
        )

    @staticmethod
    def list_cases(status: StaffCaseStatus) -> list[StaffCaseListItemDTO]:
        return [
            StaffCaseListItemDTO(
                pk=case.pk,
                kind=StaffCaseKind(case.kind),
                status=StaffCaseStatus(case.status),
                title=case.title,
                child_safety=case.child_safety,
                assignee_name=_name(case.assignee),
                created_at=case.created_at,
            )
            for case in (
                StaffCase.objects.filter(status=status)
                .select_related("assignee")
                .order_by("-created_at", "-pk")
            )
        ]

    @staticmethod
    def count_by_status() -> dict[StaffCaseStatus, int]:
        counts = dict(
            StaffCase.objects.values_list("status")
            .annotate(count=Count("pk"))
            .values_list("status", "count")
        )
        return {status: counts.get(status, 0) for status in StaffCaseStatus}

    @staticmethod
    def set_status(*, case_id: int, status: StaffCaseStatus) -> None:
        StaffCase.objects.filter(pk=case_id).update(status=status)

    @staticmethod
    def set_assignee(*, case_id: int, assignee_id: int | None) -> None:
        StaffCase.objects.filter(pk=case_id).update(assignee_id=assignee_id)

    @staticmethod
    def email_seen(message_id: str) -> int | None:
        return (
            StaffCaseEmail.objects.filter(message_id=message_id)
            .values_list("case_id", flat=True)
            .first()
        )

    @staticmethod
    def add_email(data: StaffCaseEmailCreateDict) -> None:
        StaffCaseEmail.objects.create(**data)

    @staticmethod
    def list_emails(case_id: int) -> list[EmailDTO]:
        return [
            EmailDTO(
                direction=StaffEmailDirection(email.direction),
                address=email.address,
                name=email.name,
                subject=email.subject,
                body=email.body,
                attachments=list(email.attachments),
                sent_by_name=_name(email.sent_by),
                created_at=email.created_at,
            )
            for email in StaffCaseEmail.objects.filter(case_id=case_id).select_related(
                "sent_by"
            )
        ]

    @staticmethod
    def record_decision(data: StaffCaseDecisionCreateDict) -> StaffCaseDecisionDTO:
        decision = StaffCaseDecision.objects.create(**data)
        StaffCase.objects.filter(pk=data["case_id"]).update(decision=decision)
        return _decision(
            StaffCaseDecision.objects.select_related("decided_by").get(pk=decision.pk)
        )
