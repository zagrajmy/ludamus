"""Shadowban service (Safety & Comfort): the shadowban list + signup warnings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.safety import ShadowbanSignupNotification

if TYPE_CHECKING:
    from ludamus.pacts.safety import (
        SessionShadowbanWarningDTO,
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

    def list_session_warnings(
        self, *, viewer_id: int, session_id: int
    ) -> list[SessionShadowbanWarningDTO]:
        return self._repo.list_session_shadowbanned(
            viewer_id=viewer_id, session_id=session_id
        )

    def notify_signups(
        self, *, session_id: int, signed_up: list[tuple[int, str]]
    ) -> None:
        if not signed_up:
            return
        data = self._repo.read_event_signup(
            session_id=session_id, signed_up_ids=[user_id for user_id, _ in signed_up]
        )
        if data is None or not data.hits:
            return

        name_by_id = dict(signed_up)
        names_by_presenter: dict[int, tuple[str, list[str]]] = {}
        for hit in data.hits:
            _email, names = names_by_presenter.setdefault(
                hit.presenter_id, (hit.presenter_email, [])
            )
            name = name_by_id.get(hit.banned_user_id)
            if name and name not in names:
                names.append(name)

        for presenter_id, (email, names) in names_by_presenter.items():
            self._notifier.notify_shadowbanned_signup(
                ShadowbanSignupNotification(
                    recipient_user_id=presenter_id,
                    recipient_email=email,
                    event_slug=data.event_slug,
                    event_name=data.event_name,
                    player_names=names,
                )
            )
