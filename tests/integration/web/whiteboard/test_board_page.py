from http import HTTPStatus

from django.urls import reverse

from ludamus.inits.services import Services
from ludamus.links.db.django.models import (
    BoardVisit,
    ParleyConversation,
    ParleyConversationMember,
)
from ludamus.pacts.board import BoardPageDTO
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import BoardFactory, SphereFactory, UserFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.whiteboard.conftest import LITTLE_TABLE


def _url(share_code):
    return reverse("web:boards:board", kwargs={"share_code": share_code})


def _page(board, *, is_owner, chat_id):
    return BoardPageDTO(
        pk=board.pk,
        title=board.title,
        share_code=board.share_code,
        room_url=f"{LITTLE_TABLE}/b/{board.room_code}",
        room_origin=LITTLE_TABLE,
        is_owner=is_owner,
        chat_id=chat_id,
    )


def _chat_members(board):
    return set(
        ParleyConversationMember.objects.filter(
            conversation__board_id=board.pk
        ).values_list("user_id", flat=True)
    )


class TestBoardPageView:
    def test_a_guest_with_the_link_sees_the_board_without_a_chat(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        response = client.get(_url(board.share_code))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/board.html",
            context_data={"board": _page(board, is_owner=False, chat_id=None)},
        )
        assert not BoardVisit.objects.exists()

    def test_a_member_who_opens_it_joins_its_list_and_its_chat(
        self, authenticated_client, sixteen_plus_user, sphere
    ):
        board = BoardFactory(
            sphere=sphere, creator=UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
        )

        response = authenticated_client.get(_url(board.share_code))

        chat = ParleyConversation.objects.get(board_id=board.pk)
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/board.html",
            context_data={"board": _page(board, is_owner=False, chat_id=chat.pk)},
        )
        assert BoardVisit.objects.filter(board=board, user=sixteen_plus_user).exists()
        assert _chat_members(board) == {board.creator_id, sixteen_plus_user.pk}
        [listed] = Services().parley_conversations.list_for(sixteen_plus_user.pk)
        assert (listed.kind, listed.title) == ("board", board.title)

    def test_the_frame_may_load_little_table_only(self, client, sphere, settings):
        settings.SECURE_CSP = {"default-src": ["'none'"]}
        board = BoardFactory(sphere=sphere)

        response = client.get(_url(board.share_code))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/board.html",
            context_data={"board": _page(board, is_owner=False, chat_id=None)},
            headers={
                "Content-Security-Policy": (
                    f"default-src 'none'; frame-src {LITTLE_TABLE}"
                )
            },
        )

    def test_unknown_code(self, client):
        assert_response_404(client.get(_url("missing")))

    def test_board_of_another_sphere(self, authenticated_client, active_user):
        board = BoardFactory(sphere=SphereFactory())

        response = authenticated_client.get(_url(board.share_code))

        assert_response_404(response)
        assert not BoardVisit.objects.filter(user=active_user).exists()
        assert not ParleyConversation.objects.filter(board_id=board.pk).exists()

    def test_unavailable_without_little_table(self, client, board_settings, sphere):
        board_settings.LITTLE_TABLE_URL = ""
        board = BoardFactory(sphere=sphere)

        assert_response_404(client.get(_url(board.share_code)))
