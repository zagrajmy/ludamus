from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib.messages import constants
from django.urls import reverse

from ludamus.inits.services import Services
from ludamus.links.db.django.models import (
    Board,
    ParleyConversation,
    ParleyConversationMember,
)
from ludamus.pacts.board import BoardDTO
from ludamus.pacts.parley import ParleyMemberState
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import BoardFactory, SphereFactory, UserFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_response,
    assert_response_404,
)
from tests.integration.web.whiteboard.conftest import LITTLE_TABLE

INDEX = reverse("web:boards:index")
CREATE = reverse("web:boards:create")
# About 71 bits out of letters and digits.
SHARE_CODE_LENGTH = 12
LINK_ERROR = f"Paste a Little Table board link, like {LITTLE_TABLE}/b/…."


def _edit_url(board):
    return reverse("web:boards:edit", kwargs={"pk": board.pk})


def _delete_url(board):
    return reverse("web:boards:delete", kwargs={"pk": board.pk})


class TestBoardCreatePageView:
    def test_guest_cannot_create(self, client):
        response = client.post(CREATE, {"title": "T", "room_link": "x"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={CREATE}"
        )
        assert not Board.objects.exists()

    def test_shows_the_form(self, authenticated_client):
        response = authenticated_client.get(CREATE)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/form.html",
            context_data={"form": ANY, "board": None, "little_table_url": LITTLE_TABLE},
        )

    def test_keeps_a_little_table_room_and_opens_its_page(
        self, authenticated_client, active_user, sphere
    ):
        response = authenticated_client.post(
            CREATE,
            {"title": "  Mothership  ", "room_link": f"{LITTLE_TABLE}/b/AbC12-x_9?x=1"},
        )

        board = Board.objects.get()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:boards:board", kwargs={"share_code": board.share_code}),
        )
        assert (
            board.sphere_id,
            board.creator_id,
            board.title,
            board.room_code,
            len(board.share_code),
        ) == (sphere.pk, active_user.pk, "Mothership", "AbC12-x_9", SHARE_CODE_LENGTH)
        # A chat of one would be nobody's: it opens with the second person.
        assert not ParleyConversation.objects.filter(board_id=board.pk).exists()

    @pytest.mark.parametrize(
        "link",
        (
            "https://evil.example.com/b/AbC123",
            f"{LITTLE_TABLE}/boards",
            f"{LITTLE_TABLE}/b/",
            f"{LITTLE_TABLE.replace('https', 'http')}/b/AbC123",
            "not a link",
        ),
    )
    def test_a_link_that_is_not_a_little_table_room_is_refused(
        self, authenticated_client, link
    ):
        response = authenticated_client.post(CREATE, {"title": "T", "room_link": link})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/form.html",
            context_data={
                "form": FormErrorsMatcher(room_link=[LINK_ERROR]),
                "board": None,
                "little_table_url": LITTLE_TABLE,
            },
        )
        assert not Board.objects.exists()

    def test_feature_unavailable(self, authenticated_client, board_settings):
        board_settings.LITTLE_TABLE_URL = ""

        response = authenticated_client.post(
            CREATE, {"title": "T", "room_link": "https://littletable.top/b/AbC123"}
        )

        assert_response_404(response)
        assert not Board.objects.exists()


class TestBoardEditPageView:
    def test_shows_the_owner_s_board(self, authenticated_client, active_user, sphere):
        board = BoardFactory(sphere=sphere, creator=active_user)

        response = authenticated_client.get(_edit_url(board))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/form.html",
            context_data={
                "form": ANY,
                "board": BoardDTO.model_validate(board),
                "little_table_url": LITTLE_TABLE,
            },
        )

    def test_renames_and_moves_to_another_room(
        self, authenticated_client, active_user, sphere
    ):
        board = BoardFactory(sphere=sphere, creator=active_user)

        response = authenticated_client.post(
            _edit_url(board),
            {"title": "Mothership", "room_link": f"{LITTLE_TABLE}/b/Other1/"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=INDEX,
            messages=[(constants.SUCCESS, "Board saved.")],
        )
        board.refresh_from_db()
        assert (board.title, board.room_code) == ("Mothership", "Other1")

    def test_a_foreign_link_is_refused(self, authenticated_client, active_user, sphere):
        board = BoardFactory(sphere=sphere, creator=active_user, room_code="Before")

        response = authenticated_client.post(
            _edit_url(board),
            {"title": "T", "room_link": "https://evil.example.com/b/After"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/form.html",
            context_data={
                "form": FormErrorsMatcher(room_link=[LINK_ERROR]),
                "board": BoardDTO.model_validate(board),
                "little_table_url": LITTLE_TABLE,
            },
        )
        board.refresh_from_db()
        assert board.room_code == "Before"

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_not_the_creator(self, authenticated_client, sphere, method):
        board = BoardFactory(sphere=sphere, title="Before")

        response = getattr(authenticated_client, method)(
            _edit_url(board),
            {"title": "Hijacked", "room_link": f"{LITTLE_TABLE}/b/Hijacked"},
        )

        assert_response_404(response)
        board.refresh_from_db()
        assert board.title == "Before"

    def test_own_board_in_another_sphere(self, authenticated_client, active_user):
        board = BoardFactory(sphere=SphereFactory(), creator=active_user, title="B")

        response = authenticated_client.post(
            _edit_url(board), {"title": "Moved", "room_link": f"{LITTLE_TABLE}/b/M"}
        )

        assert_response_404(response)
        board.refresh_from_db()
        assert board.title == "B"


class TestBoardDeleteActionView:
    def test_deletes_and_empties_its_chat(
        self, authenticated_client, sixteen_plus_user, sphere
    ):
        board = BoardFactory(sphere=sphere, creator=sixteen_plus_user)
        visitor = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
        Services().boards.open(
            share_code=board.share_code,
            sphere_id=sphere.pk,
            user_id=visitor.pk,
            now=datetime.now(UTC),
        )
        assert set(
            ParleyConversationMember.objects.filter(
                conversation__board_id=board.pk, state=ParleyMemberState.ACTIVE
            ).values_list("user_id", flat=True)
        ) == {sixteen_plus_user.pk, visitor.pk}

        response = authenticated_client.post(_delete_url(board))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=INDEX,
            messages=[(constants.SUCCESS, "Board deleted.")],
        )
        assert not Board.objects.exists()
        # The chat's record stays for any report made in it; nobody is in it.
        chat = ParleyConversation.objects.get(board_id=board.pk)
        assert set(chat.members.values_list("state", flat=True)) == {
            ParleyMemberState.LEFT
        }

    def test_not_the_creator(self, authenticated_client, sphere):
        board = BoardFactory(sphere=sphere)

        assert_response_404(authenticated_client.post(_delete_url(board)))
        assert Board.objects.filter(pk=board.pk).exists()

    def test_own_board_in_another_sphere(self, authenticated_client, active_user):
        board = BoardFactory(sphere=SphereFactory(), creator=active_user)

        assert_response_404(authenticated_client.post(_delete_url(board)))
        assert Board.objects.filter(pk=board.pk).exists()

    def test_requires_post(self, authenticated_client, active_user, sphere):
        board = BoardFactory(sphere=sphere, creator=active_user)

        assert_response(
            authenticated_client.get(_delete_url(board)), HTTPStatus.METHOD_NOT_ALLOWED
        )
