from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.db.models import (
    BooleanField,
    CharField,
    Count,
    Exists,
    ExpressionWrapper,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce, NullIf

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
    CaseStatus,
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
    CaseKind,
    CaseNoticeDTO,
    CaseVerdictDTO,
    InboxCaseDTO,
    StaffCaseRepositoryProtocol,
    StaffMemberDTO,
)
from ludamus.pacts.user import AgeBand

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django_stubs_ext import WithAnnotations

    from ludamus.pacts.staff_cases import CaseEmailCreateDict, EmailCaseCreateDict

    class _Derived(TypedDict):
        has_notices: bool
        has_reports: bool
        child_safety: bool
        shown_title: str

    type _Case = WithAnnotations[ModerationCase, _Derived]

_PRESENT = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)
_THREAD_TITLE_MAX_LENGTH = 80
_MINOR = AgeBand.THIRTEEN_TO_FIFTEEN.value


def _staff() -> Q:
    return Q(is_staff=True, is_active=True)


def _name(user: User | None) -> str:
    return "" if user is None else user.get_full_name()


def _cases(urgent: frozenset[NoticeCategory]) -> QuerySet[_Case]:
    """Cases with what the inbox derives from their records, in one query."""
    notices = ContentNotice.objects.filter(case=OuterRef("pk"))
    reports = ParleyReport.objects.filter(case=OuterRef("pk"))
    teen_in_report = (
        Q(reporter__age_band=_MINOR)
        | Q(reported_user__age_band=_MINOR)
        | Q(
            conversation__members__user__age_band=_MINOR,
            conversation__members__state__in=_PRESENT,
        )
    )
    return ModerationCase.objects.select_related("assignee", "decided_by").annotate(
        has_notices=Exists(notices),
        has_reports=Exists(reports),
        child_safety=ExpressionWrapper(
            Q(Exists(notices.filter(category__in=urgent)))
            | Q(Exists(reports.filter(teen_in_report))),
            output_field=BooleanField(),
        ),
        shown_title=Coalesce(
            NullIf("title", Value("")),
            Subquery(notices.order_by("pk").values("explanation")[:1]),
            Subquery(reports.order_by("pk").values("reason")[:1]),
            Value(""),
            output_field=CharField(),
        ),
    )


def _kind(case: _Case) -> CaseKind:
    if case.has_notices:
        return CaseKind.NOTICE
    if case.has_reports:
        return CaseKind.CHAT_REPORT
    return CaseKind.EMAIL if case.external_email else CaseKind.STATEMENT


def _row(case: _Case) -> InboxCaseDTO:
    return InboxCaseDTO(
        pk=case.pk,
        kind=_kind(case),
        status=CaseStatus(case.status),
        title=case.shown_title,
        child_safety=case.child_safety,
        assignee_name=_name(case.assignee),
        created_at=case.created_at,
    )


def _reply_to(
    case: ModerationCase, *, notices: list[ContentNotice], reports: list[ParleyReport]
) -> tuple[str, str]:
    """Answer the last of the case's own people who wrote in, else who opened it.

    The case's own people are its sender, reporters and the people its
    statements went to. Anyone else can put "[Z-n]" in a subject; their mail is
    filed, but replies never go to them.
    """
    people = {
        case.external_email: case.external_name,
        **{n.reporter_email: n.reporter_name for n in notices if n.reporter_email},
        **{r.reporter.email: _name(r.reporter) for r in reports if r.reporter.email},
    }
    people.pop("", None)
    known = {address.casefold() for address in people} | {
        address.casefold()
        for address in User.objects.filter(
            statements_of_reasons__case=case
        ).values_list("email", flat=True)
        if address
    }
    last = (
        case.emails.filter(direction=CaseEmail.Direction.IN)
        .order_by("-created_at", "-pk")
        .values_list("address", "name")
    )
    for address, name in last:
        if address.casefold() in known:
            return address, name
    return next(iter(people.items()), ("", ""))


def _verdict(
    notices: list[ContentNotice], reports: list[ParleyReport]
) -> CaseVerdictDTO | None:
    decided = [
        (record.status, record.decision, record.ground, record.decision_text)
        for record in notices
        if record.status != ModerationStatus.OPEN
    ] + [
        (record.status, record.decision, record.ground, record.decision_text)
        for record in reports
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


def _report(report: ParleyReport) -> CaseChatReportDTO:
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
        title = (
            _cases(frozenset()).values_list("shown_title", flat=True).get(pk=case_id)
        )
        thread = ParleyConversation.objects.create(
            kind=ParleyConversationKind.STAFF,
            title=f"{case_reference(case_id)} {title}"[
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
    def read(case_id: int, *, urgent: frozenset[NoticeCategory]) -> CaseDTO:
        case = (
            _cases(urgent)
            .prefetch_related(
                Prefetch("notices", queryset=ContentNotice.objects.order_by("pk")),
                Prefetch(
                    "chat_reports",
                    queryset=ParleyReport.objects.select_related(
                        "reporter", "reported_user"
                    ).order_by("pk"),
                ),
            )
            .filter(pk=case_id)
            .first()
        )
        if case is None:
            raise NotFoundError
        notices, reports = list(case.notices.all()), list(case.chat_reports.all())
        reply_to, reply_name = _reply_to(case, notices=notices, reports=reports)
        return CaseDTO(
            **_row(case).model_dump(),
            assignee_id=case.assignee_id,
            decided_by_name=_name(case.decided_by),
            thread_id=case.thread_id,
            reply_to=reply_to,
            reply_name=reply_name,
            notices=[
                CaseNoticeDTO(
                    pk=notice.pk,
                    url=notice.url,
                    category=NoticeCategory(notice.category),
                    explanation=notice.explanation,
                    reporter_name=notice.reporter_name,
                    status=ModerationStatus(notice.status),
                )
                for notice in notices
            ],
            chat_reports=[_report(report) for report in reports],
            verdict=_verdict(notices, reports),
        )

    @staticmethod
    def list_cases(
        status: CaseStatus,
        *,
        urgent: frozenset[NoticeCategory],
        limit: int,
        offset: int,
    ) -> list[InboxCaseDTO]:
        return [
            _row(case)
            for case in (
                _cases(urgent)
                .filter(status=status)
                .order_by("-child_safety", "-created_at", "-pk")[
                    offset : offset + limit
                ]
            )
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
