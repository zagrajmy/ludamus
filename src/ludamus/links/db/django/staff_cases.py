from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count, Prefetch, Q

from ludamus.links.db.django.models import (
    CaseEmail,
    ContentNotice,
    ModerationCase,
    ParleyConversation,
    ParleyConversationMember,
    ParleyReport,
    User,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.moderation import (
    ModerationDecision,
    ModerationGround,
    ModerationStatus,
    NoticeCategory,
    case_reference,
)
from ludamus.pacts.parley import ParleyConversationKind, ParleyMemberState
from ludamus.pacts.staff_cases import (
    CaseChatReportDTO,
    CaseDTO,
    CaseEmailDirection,
    CaseEmailDTO,
    CaseNoticeDTO,
    CaseRowDTO,
    CaseStatus,
    CaseVerdictDTO,
    StaffCaseRepositoryProtocol,
    StaffMemberDTO,
)
from ludamus.pacts.user import AgeBand

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from ludamus.pacts.staff_cases import CaseEmailCreateDict, EmailCaseCreateDict

_PRESENT = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)
_THREAD_TITLE_MAX_LENGTH = 80
_MINOR = AgeBand.THIRTEEN_TO_FIFTEEN.value


def _staff() -> Q:
    return Q(is_staff=True, is_active=True)


def _name(user: User | None) -> str:
    return "" if user is None else user.get_full_name()


def _minor_involved() -> Q:
    """Match a report whose reporter, author or conversation holds a 13–15."""
    return (
        Q(reporter__age_band=_MINOR)
        | Q(reported_user__age_band=_MINOR)
        | Q(
            conversation__members__user__age_band=_MINOR,
            conversation__members__state__in=_PRESENT,
        )
    )


def _reports_with_minors(case_ids: list[int]) -> set[int]:
    return set(
        ParleyReport.objects.filter(_minor_involved(), case_id__in=case_ids)
        .values_list("pk", flat=True)
        .distinct()
    )


def _title(case: ModerationCase) -> str:
    notices = list(case.notices.all())
    reports = list(case.chat_reports.all())
    if case.title:
        return case.title
    if notices:
        return notices[0].explanation or notices[0].url
    return reports[0].reason if reports else ""


def _reply_to(case: ModerationCase) -> tuple[str, str]:
    """Whoever last wrote in, else the sender, notice reporter or chat reporter."""
    if (
        last := case.emails.filter(direction=CaseEmail.Direction.IN).last()
    ) is not None:
        return last.address, last.name
    if case.external_email:
        return case.external_email, case.external_name
    if notice := next((n for n in case.notices.all() if n.reporter_email), None):
        return notice.reporter_email, notice.reporter_name
    if report := next((r for r in case.chat_reports.all() if r.reporter.email), None):
        return report.reporter.email, _name(report.reporter)
    return "", ""


def _verdict(case: ModerationCase) -> CaseVerdictDTO | None:
    decided = [
        (record.status, record.decision, record.ground, record.decision_text)
        for record in case.notices.all()
        if record.status != ModerationStatus.OPEN
    ] + [
        (record.status, record.decision, record.ground, record.decision_text)
        for record in case.chat_reports.all()
        if record.status != ModerationStatus.OPEN
    ]
    if not decided:
        return None
    status, decision, ground, text = decided[0]
    return CaseVerdictDTO(
        status=ModerationStatus(status),
        decision=ModerationDecision(decision),
        ground=ModerationGround(ground) if ground else None,
        decision_text=text,
    )


def _report(report: ParleyReport, *, minors: set[int]) -> CaseChatReportDTO:
    author = report.reported_user
    return CaseChatReportDTO(
        pk=report.pk,
        room_id=report.room_id,
        reason=report.reason,
        reporter_name=_name(report.reporter),
        author_name=report.author_name or _name(author),
        author_age_band=None if author is None else AgeBand(author.age_band),
        author_joined_at=None if author is None else author.date_joined,
        body=report.body,
        written_at=report.written_at,
        status=ModerationStatus(report.status),
        involves_minor=report.pk in minors,
    )


def _cases() -> QuerySet[ModerationCase]:
    return ModerationCase.objects.select_related(
        "assignee", "decided_by"
    ).prefetch_related(
        Prefetch("notices", queryset=ContentNotice.objects.order_by("pk")),
        Prefetch(
            "chat_reports",
            queryset=ParleyReport.objects.select_related(
                "reporter", "reported_user"
            ).order_by("pk"),
        ),
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
    def open_for_email(data: EmailCaseCreateDict) -> int:
        return ModerationCase.objects.create(**data).pk

    @staticmethod
    def open_thread(case_id: int) -> int:
        case = ModerationCase.objects.get(pk=case_id)
        thread = ParleyConversation.objects.create(
            kind=ParleyConversationKind.STAFF,
            title=f"{case_reference(case_id)} {_title(case)}"[
                :_THREAD_TITLE_MAX_LENGTH
            ].strip(),
        )
        if ModerationCase.objects.filter(pk=case_id, thread__isnull=True).update(
            thread=thread
        ):
            return thread.pk
        # NOTE: another request gave the case its thread first; keep that one.
        thread.delete()
        return ModerationCase.objects.values_list("thread_id", flat=True).get(
            pk=case_id
        )

    @staticmethod
    def set_thread_members(
        *, user_ids: list[int], thread_ids: list[int] | None
    ) -> list[int]:
        threads = ParleyConversation.objects.filter(kind=ParleyConversationKind.STAFF)
        if thread_ids is not None:
            threads = threads.filter(pk__in=thread_ids)
        present: dict[int, set[int]] = {
            pk: set() for pk in threads.values_list("pk", flat=True)
        }
        for thread_id, user_id in ParleyConversationMember.objects.filter(
            conversation_id__in=present, state__in=_PRESENT
        ).values_list("conversation_id", "user_id"):
            present[thread_id].add(user_id)
        wanted = set(user_ids)
        changed = sorted(pk for pk, users in present.items() if users != wanted)
        ParleyConversationMember.objects.filter(
            conversation_id__in=changed, state__in=_PRESENT
        ).exclude(user_id__in=wanted).update(state=ParleyMemberState.LEFT)
        for thread_id in changed:
            for user_id in wanted - present[thread_id]:
                ParleyConversationMember.objects.update_or_create(
                    conversation_id=thread_id,
                    user_id=user_id,
                    defaults={"state": ParleyMemberState.ACTIVE, "is_admin": False},
                )
        return changed

    @staticmethod
    def read(case_id: int) -> CaseDTO:
        if (case := _cases().filter(pk=case_id).first()) is None:
            raise NotFoundError
        reply_to, reply_name = _reply_to(case)
        minors = _reports_with_minors([case.pk])
        return CaseDTO(
            pk=case.pk,
            status=CaseStatus(case.status),
            title=_title(case),
            assignee_id=case.assignee_id,
            decided_by_name=_name(case.decided_by),
            thread_id=case.thread_id,
            reply_to=reply_to,
            reply_name=reply_name,
            opened_by_email=bool(case.external_email),
            notices=[
                CaseNoticeDTO(
                    pk=notice.pk,
                    url=notice.url,
                    category=NoticeCategory(notice.category),
                    explanation=notice.explanation,
                    reporter_name=notice.reporter_name,
                    status=ModerationStatus(notice.status),
                )
                for notice in case.notices.all()
            ],
            chat_reports=[
                _report(report, minors=minors) for report in case.chat_reports.all()
            ],
            verdict=_verdict(case),
            created_at=case.created_at,
        )

    @staticmethod
    def list_cases(status: CaseStatus) -> list[CaseRowDTO]:
        cases = list(_cases().filter(status=status).order_by("-created_at", "-pk"))
        minors = _reports_with_minors([case.pk for case in cases])
        return [
            CaseRowDTO(
                pk=case.pk,
                status=CaseStatus(case.status),
                title=_title(case),
                assignee_name=_name(case.assignee),
                created_at=case.created_at,
                has_notices=bool(case.notices.all()),
                has_chat_reports=bool(case.chat_reports.all()),
                opened_by_email=bool(case.external_email),
                notice_categories=[
                    NoticeCategory(notice.category) for notice in case.notices.all()
                ],
                involves_minor=any(r.pk in minors for r in case.chat_reports.all()),
            )
            for case in cases
        ]

    @staticmethod
    def count_by_status() -> dict[CaseStatus, int]:
        counts = dict(
            ModerationCase.objects.values_list("status")
            .annotate(count=Count("pk"))
            .values_list("status", "count")
        )
        return {status: counts.get(status, 0) for status in CaseStatus}

    @staticmethod
    def set_status(*, case_id: int, status: CaseStatus) -> None:
        ModerationCase.objects.filter(pk=case_id).update(status=status)

    @staticmethod
    def set_assignee(*, case_id: int, assignee_id: int | None) -> None:
        ModerationCase.objects.filter(pk=case_id).update(assignee_id=assignee_id)

    @staticmethod
    def set_decided_by(*, case_id: int, user_id: int) -> None:
        ModerationCase.objects.filter(pk=case_id).update(decided_by_id=user_id)

    @staticmethod
    def email_seen(message_id: str) -> int | None:
        return (
            CaseEmail.objects.filter(message_id=message_id)
            .values_list("case_id", flat=True)
            .first()
        )

    @staticmethod
    def add_email(data: CaseEmailCreateDict) -> None:
        CaseEmail.objects.create(**data)

    @staticmethod
    def list_emails(case_id: int) -> list[CaseEmailDTO]:
        return [
            CaseEmailDTO(
                direction=CaseEmailDirection(email.direction),
                address=email.address,
                name=email.name,
                subject=email.subject,
                body=email.body,
                attachments=list(email.attachments),
                sent_by_name=_name(email.sent_by),
                created_at=email.created_at,
            )
            for email in CaseEmail.objects.filter(case_id=case_id).select_related(
                "sent_by"
            )
        ]

    @staticmethod
    def find_account(identifier: str) -> int | None:
        matches = list(
            User.objects.filter(
                Q(username=identifier)
                | Q(email__iexact=identifier)
                | Q(slug=identifier)
            ).values_list("pk", flat=True)[:2]
        )
        return matches[0] if len(matches) == 1 else None
