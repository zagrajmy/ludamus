from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.safety import ShadowbanSignupNotification

if TYPE_CHECKING:
    from ludamus.pacts.ids import EventBanId, EventId, SessionId, UserId
    from ludamus.pacts.safety import (
        EventBanDTO,
        EventBanRepositoryProtocol,
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

    def list_candidates(self, owner_id: UserId) -> list[ShadowbanCandidateDTO]:
        return self._repo.list_candidates(owner_id)

    def banned_user_ids(self, owner_id: UserId) -> set[UserId]:
        # Players this user shadowbanned — for red-ring avatars and the
        # enrolment skip (a presenter can't have banned players seated).
        return self._repo.banned_user_ids(owner_id)

    def banning_owner_ids(self, target_id: UserId) -> set[UserId]:
        return self._repo.banning_owner_ids(target_id)

    def set_shadowban(
        self, *, owner_id: UserId, target_slug: str, banned: bool
    ) -> None:
        with self._transaction.atomic():
            self._repo.set_shadowban(
                owner_id=owner_id, target_slug=target_slug, banned=banned
            )

    def add_by_identifier(self, *, owner_id: UserId, identifier: str) -> bool:
        if not (identifier := identifier.strip()):
            return False
        with self._transaction.atomic():
            return self._repo.shadowban_by_identifier(
                owner_id=owner_id, identifier=identifier
            )

    def list_session_warnings(
        self, *, viewer_id: UserId, session_id: SessionId
    ) -> list[SessionShadowbanWarningDTO]:
        return self._repo.list_session_shadowbanned(
            viewer_id=viewer_id, session_id=session_id
        )

    def notify_signups(
        self, *, session_id: SessionId, signed_up: list[tuple[UserId, str]]
    ) -> None:
        if not signed_up:
            return
        data = self._repo.read_event_signup(
            session_id=session_id, signed_up_ids=[user_id for user_id, _ in signed_up]
        )
        if data is None or not data.hits:
            return

        name_by_id = dict(signed_up)
        names_by_recipient: dict[UserId, tuple[list[str], list[str]]] = {}
        seen_by_recipient: dict[UserId, set[UserId]] = {}
        for hit in data.hits:
            event_names, session_names = names_by_recipient.setdefault(
                hit.recipient_id, ([], [])
            )
            seen = seen_by_recipient.setdefault(hit.recipient_id, set())
            # Dedupe by banned user id, not name: two distinct players sharing
            # a display name must both be reported.
            if hit.banned_user_id in seen:
                continue
            seen.add(hit.banned_user_id)
            if name := name_by_id.get(hit.banned_user_id):
                (session_names if hit.in_session else event_names).append(name)

        for recipient_id, (event_names, session_names) in names_by_recipient.items():
            if not event_names and not session_names:
                continue
            self._notifier.notify_shadowbanned_signup(
                ShadowbanSignupNotification(
                    recipient_user_id=recipient_id,
                    event_slug=data.event_slug,
                    event_name=data.event_name,
                    session_title=data.session_title,
                    sphere_domain=data.sphere_domain,
                    player_names=event_names,
                    session_player_names=session_names,
                )
            )


class EventBanService:
    def __init__(
        self, transaction: TransactionProtocol, repo: EventBanRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._repo = repo

    def list_for_event(self, event_id: EventId) -> list[EventBanDTO]:
        return self._repo.list_by_event(event_id)

    def is_banned(self, *, event_id: EventId, user_id: UserId) -> bool:
        return self._repo.is_banned(event_id=event_id, user_id=user_id)

    def banned_event_ids(
        self, *, event_ids: set[EventId], user_id: UserId
    ) -> set[EventId]:
        return self._repo.banned_event_ids(event_ids=event_ids, user_id=user_id)

    def ban(self, *, event_id: EventId, identifier: str, reason: str) -> bool:
        if not (identifier := identifier.strip()):
            return False
        with self._transaction.atomic():
            return self._repo.ban(
                event_id=event_id, identifier=identifier, reason=reason.strip()
            )

    def unban(self, *, event_id: EventId, ban_id: EventBanId) -> None:
        with self._transaction.atomic():
            self._repo.unban(event_id=event_id, ban_id=ban_id)
