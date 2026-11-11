from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.session_cards import SessionModalServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.ids import EventId, SessionId, UserId
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.session_cards import (
        SessionModalDTO,
        SessionModalRepositoryProtocol,
    )


class SessionModalService(SessionModalServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        sessions: SessionModalRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions

    def read(
        self,
        *,
        event_id: EventId,
        session_id: SessionId,
        viewer_user_ids: list[UserId],
        editor_user_id: UserId | None,
    ) -> SessionModalDTO | None:
        with self._transaction.atomic():
            return self._sessions.read_modal(
                event_id=event_id,
                session_id=session_id,
                viewer_user_ids=viewer_user_ids,
                editor_user_id=editor_user_id,
            )
