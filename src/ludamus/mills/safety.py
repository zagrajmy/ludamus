"""Shadowban service (Safety & Comfort).

Owns the proposer's personal shadowban list and the decision to warn them when
a shadowbanned player signs up to one of their sessions. IO is delegated to the
injected repository and notifier ports so the logic stays unit-testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.safety import ShadowbanSignupNotification

if TYPE_CHECKING:
    from ludamus.pacts.safety import (
        ShadowbanCandidateDTO,
        ShadowbanNotifierProtocol,
        ShadowbanRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class ShadowbanService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        repo: ShadowbanRepositoryProtocol,
        notifier: ShadowbanNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._repo = repo
        self._notifier = notifier

    def list_candidates(self, owner_id: int) -> list[ShadowbanCandidateDTO]:
        return self._repo.list_candidates(owner_id)

    def set_shadowban(self, *, owner_id: int, target_slug: str, banned: bool) -> None:
        with self._transaction.atomic():
            self._repo.set_shadowban(
                owner_id=owner_id, target_slug=target_slug, banned=banned
            )

    def add_by_identifier(self, *, owner_id: int, identifier: str) -> bool:
        if not (identifier := identifier.strip()):
            return False
        with self._transaction.atomic():
            return self._repo.shadowban_by_identifier(
                owner_id=owner_id, identifier=identifier
            )

    def notify_signups(
        self, *, session_id: int, signed_up: list[tuple[int, str]]
    ) -> None:
        if not signed_up:
            return
        if (target := self._repo.read_signup_target(session_id)) is None:
            return
        banned = self._repo.shadowbanned_user_ids(target.presenter_id)
        offenders = [name for user_id, name in signed_up if user_id in banned]
        if not offenders:
            return
        self._notifier.notify_shadowbanned_signup(
            ShadowbanSignupNotification(
                recipient_user_id=target.presenter_id,
                recipient_email=target.presenter_email,
                session_id=session_id,
                session_title=target.session_title,
                player_names=offenders,
            )
        )
