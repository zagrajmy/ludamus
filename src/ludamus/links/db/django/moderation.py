from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from ludamus.links.db.django.models import (
    ContentNotice,
    ModerationCase,
    ParleyReport,
    SessionParticipation,
    StatementOfReasons,
    User,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.moderation import (
    ActiveRecipientsRepositoryProtocol,
    CaseStatus,
    ChatReportDTO,
    ChatReportRepositoryProtocol,
    ContentNoticeDTO,
    ContentNoticeRepositoryProtocol,
    ModerationCaseRepositoryProtocol,
    ModerationStatus,
    StatementOfReasonsRepositoryProtocol,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.moderation import (
        ContentNoticeCreateDict,
        ModerationDecisionDict,
        StatementOfReasonsCreateDict,
    )


class ModerationCaseRepository(ModerationCaseRepositoryProtocol):
    @staticmethod
    def open(*, status: CaseStatus) -> int:
        return ModerationCase.objects.create(status=status).pk


class ContentNoticeRepository(ContentNoticeRepositoryProtocol):
    @staticmethod
    def create(data: ContentNoticeCreateDict) -> ContentNoticeDTO:
        return ContentNoticeDTO.model_validate(ContentNotice.objects.create(**data))

    @staticmethod
    def read(pk: int) -> ContentNoticeDTO:
        try:
            return ContentNoticeDTO.model_validate(ContentNotice.objects.get(pk=pk))
        except ContentNotice.DoesNotExist as exception:
            raise NotFoundError from exception

    @staticmethod
    def decide(pk: int, decision: ModerationDecisionDict) -> bool:
        return bool(
            ContentNotice.objects.filter(pk=pk, status=ModerationStatus.OPEN).update(
                **decision
            )
        )


class ChatReportRepository(ChatReportRepositoryProtocol):
    @staticmethod
    def read_by_message(
        *, reporter_id: int, room_id: str, message_id: int
    ) -> ChatReportDTO | None:
        report = ParleyReport.objects.filter(
            reporter_id=reporter_id, room_id=room_id, message_id=message_id
        ).first()
        return None if report is None else ChatReportDTO.model_validate(report)

    @staticmethod
    def read(pk: int) -> ChatReportDTO:
        try:
            return ChatReportDTO.model_validate(ParleyReport.objects.get(pk=pk))
        except ParleyReport.DoesNotExist as exception:
            raise NotFoundError from exception

    @staticmethod
    def case_of_message(*, room_id: str, message_id: int) -> int | None:
        return (
            ParleyReport.objects.filter(
                room_id=room_id, message_id=message_id, case__isnull=False
            )
            .order_by("pk")
            .values_list("case_id", flat=True)
            .first()
        )

    @staticmethod
    def attach_case(*, pk: int, case_id: int) -> bool:
        return bool(
            ParleyReport.objects.filter(pk=pk, case__isnull=True).update(
                case_id=case_id
            )
        )

    @staticmethod
    def decide(pk: int, decision: ModerationDecisionDict) -> bool:
        return bool(
            ParleyReport.objects.filter(pk=pk, status=ModerationStatus.OPEN).update(
                **decision
            )
        )


class StatementOfReasonsRepository(StatementOfReasonsRepositoryProtocol):
    @staticmethod
    def create(data: StatementOfReasonsCreateDict) -> int:
        return StatementOfReasons.objects.create(**data).pk

    @staticmethod
    def exists(*, case_id: int, user_id: int) -> bool:
        return StatementOfReasons.objects.filter(
            case_id=case_id, user_id=user_id
        ).exists()


class ActiveRecipientsRepository(ActiveRecipientsRepositoryProtocol):
    @staticmethod
    def count_active_accounts(*, start: datetime, end: datetime) -> int:
        enrolled = SessionParticipation.objects.filter(
            creation_time__gte=start, creation_time__lt=end
        ).values("user_id")
        return User.objects.filter(
            Q(last_login__gte=start, last_login__lt=end) | Q(pk__in=enrolled)
        ).count()
