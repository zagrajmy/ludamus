from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.chronology import SessionModalServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.chronology import SessionModalDTO, SessionModalRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol


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
        event_id: int,
        session_id: int,
        viewer_user_ids: list[int],
        editor_user_id: int | None,
    ) -> SessionModalDTO | None:
        with self._transaction.atomic():
            return self._sessions.read_modal(
                event_id=event_id,
                session_id=session_id,
                viewer_user_ids=viewer_user_ids,
                editor_user_id=editor_user_id,
            )
