from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import ParleyMentionMail, User
from ludamus.pacts.parley_mentions import (
    ParleyMentionRecipientDTO,
    ParleyMentionRepositoryProtocol,
)
from ludamus.pacts.user import UserType

if TYPE_CHECKING:
    from datetime import datetime


class ParleyMentionRepository(ParleyMentionRepositoryProtocol):
    @staticmethod
    def read_recipient(user_id: int) -> ParleyMentionRecipientDTO | None:
        user = (
            User.objects.filter(pk=user_id)
            .only("is_active", "user_type", "email", "email_verified")
            .first()
        )
        if user is None:
            return None
        mail = ParleyMentionMail.objects.filter(user_id=user_id).first()
        return ParleyMentionRecipientDTO(
            active=user.is_active and user.user_type == UserType.ACTIVE,
            mailable=bool(user.email) and user.email_verified,
            enabled=mail is None or mail.enabled,
            last_sent_at=None if mail is None else mail.last_sent_at,
        )

    @staticmethod
    def read_names(user_ids: set[int]) -> dict[int, str]:
        return {
            user.pk: user.get_full_name()
            for user in User.objects.filter(pk__in=user_ids).only("name")
        }

    @staticmethod
    def record_sent(*, user_id: int, at: datetime) -> None:
        ParleyMentionMail.objects.update_or_create(
            user_id=user_id, defaults={"last_sent_at": at}
        )

    @staticmethod
    def read_enabled(user_id: int) -> bool:
        return not ParleyMentionMail.objects.filter(
            user_id=user_id, enabled=False
        ).exists()

    @staticmethod
    def set_enabled(*, user_id: int, enabled: bool) -> None:
        ParleyMentionMail.objects.update_or_create(
            user_id=user_id, defaults={"enabled": enabled}
        )
