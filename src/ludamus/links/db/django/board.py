"""Board records and who has opened them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from ludamus.links.db.django.models import Board, BoardVisit, User
from ludamus.pacts.board import BoardDTO, BoardListItemDTO, BoardRepositoryProtocol
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.ids import UserId


def _get(**lookup: int | str) -> Board:
    try:
        return Board.objects.get(**lookup)
    except Board.DoesNotExist as exception:
        raise NotFoundError from exception


class BoardRepository(BoardRepositoryProtocol):
    @staticmethod
    def create(
        *, sphere_id: int, creator_id: UserId, title: str, share_code: str
    ) -> BoardDTO:
        return BoardDTO.model_validate(
            Board.objects.create(
                sphere_id=sphere_id,
                creator_id=creator_id,
                title=title,
                share_code=share_code,
            )
        )

    @staticmethod
    def read_by_share_code(*, share_code: str, sphere_id: int) -> BoardDTO:
        return BoardDTO.model_validate(_get(share_code=share_code, sphere_id=sphere_id))

    @staticmethod
    def read_owned(*, pk: int, sphere_id: int, creator_id: UserId) -> BoardDTO:
        return BoardDTO.model_validate(
            _get(pk=pk, sphere_id=sphere_id, creator_id=creator_id)
        )

    @staticmethod
    def rename(*, pk: int, title: str) -> None:
        board = _get(pk=pk)
        board.title = title
        board.save(update_fields=["title", "modification_time"])

    @staticmethod
    def reset_link(*, pk: int, share_code: str) -> BoardDTO:
        board = Board.objects.select_for_update().get(pk=pk)
        board.share_code = share_code
        board.link_version = F("link_version") + 1
        board.save(update_fields=["share_code", "link_version", "modification_time"])
        board.refresh_from_db()
        return BoardDTO.model_validate(board)

    @staticmethod
    def delete(pk: int) -> None:
        Board.objects.filter(pk=pk).delete()

    @staticmethod
    def record_visit(*, pk: int, user_id: UserId, now: datetime) -> None:
        BoardVisit.objects.update_or_create(
            board_id=pk, user_id=user_id, defaults={"last_opened_at": now}
        )

    @staticmethod
    def list_for(*, sphere_id: int, user_id: UserId) -> list[BoardListItemDTO]:
        own_visit = BoardVisit.objects.filter(board=OuterRef("pk"), user_id=user_id)
        boards = (
            Board.objects.filter(sphere_id=sphere_id)
            .filter(
                Q(creator_id=user_id)
                | Q(
                    pk__in=BoardVisit.objects.filter(user_id=user_id).values("board_id")
                )
            )
            .annotate(
                opened_at=Coalesce(
                    Subquery(own_visit.values("last_opened_at")[:1]), "creation_time"
                )
            )
            .order_by("-opened_at", "-pk")
            .values("pk", "title", "share_code", "creator_id", "opened_at")
        )
        return [
            BoardListItemDTO(
                pk=board["pk"],
                title=board["title"],
                share_code=board["share_code"],
                is_owner=board["creator_id"] == user_id,
                last_opened_at=board["opened_at"],
            )
            for board in boards
        ]

    @staticmethod
    def read_user_name(user_id: UserId) -> str:
        try:
            return User.objects.get(pk=user_id).get_full_name()
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
