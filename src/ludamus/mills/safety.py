from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.safety import ShadowbanSignupNotification

if TYPE_CHECKING:
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

    def list_candidates(self, owner_id: int) -> list[ShadowbanCandidateDTO]:
        return self._repo.list_candidates(owner_id)

    def banned_user_ids(self, owner_id: int) -> set[int]:
        # Players this user shadowbanned — for red-ring avatars and the
        # enrolment skip (a presenter can't have banned players seated).
        return self._repo.banned_user_ids(owner_id)

    def banning_owner_ids(self, target_id: int) -> set[int]:
        # Users who shadowbanned this target — the view hides their sessions.
        return self._repo.banning_owner_ids(target_id)

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
        seen_by_presenter: dict[int, set[int]] = {}
        for hit in data.hits:
            _email, names = names_by_presenter.setdefault(
                hit.presenter_id, (hit.presenter_email, [])
            )
            seen = seen_by_presenter.setdefault(hit.presenter_id, set())
            # Dedupe by banned user id, not name: two distinct players sharing
            # a display name must both be reported.
            if hit.banned_user_id in seen:
                continue
            seen.add(hit.banned_user_id)
            if name := name_by_id.get(hit.banned_user_id):
                names.append(name)

        for presenter_id, (email, names) in names_by_presenter.items():
            if not names:
                continue
            self._notifier.notify_shadowbanned_signup(
                ShadowbanSignupNotification(
                    recipient_user_id=presenter_id,
                    recipient_email=email,
                    event_slug=data.event_slug,
                    event_name=data.event_name,
                    player_names=names,
                )
            )


class EventBanService:
    def __init__(
        self, transaction: TransactionProtocol, repo: EventBanRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._repo = repo

    def list_for_event(self, event_id: int) -> list[EventBanDTO]:
        return self._repo.list_by_event(event_id)

    def is_banned(self, *, event_id: int, user_id: int) -> bool:
        return self._repo.is_banned(event_id=event_id, user_id=user_id)

    def ban(self, *, event_id: int, identifier: str, reason: str) -> bool:
        if not (identifier := identifier.strip()):
            return False
        with self._transaction.atomic():
            return self._repo.ban(
                event_id=event_id, identifier=identifier, reason=reason.strip()
            )

    def unban(self, *, event_id: int, ban_id: int) -> None:
        with self._transaction.atomic():
            self._repo.unban(event_id=event_id, ban_id=ban_id)
