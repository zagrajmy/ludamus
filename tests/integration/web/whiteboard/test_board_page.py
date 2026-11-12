from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import BoardVisit
from tests.integration.conftest import BoardFactory, SphereFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.whiteboard.helpers import board_dto


def _url(share_code):
    return reverse("web:boards:board", kwargs={"share_code": share_code})


class TestBoardPageView:
    def test_guest_opens_the_board_and_leaves_no_visit(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        response = client.get(_url(board.share_code))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/board.html",
            context_data={
                "board": board_dto(board),
                "is_owner": False,
                "license_key": "",
            },
        )
        assert not BoardVisit.objects.exists()

    def test_member_visit_puts_it_on_their_list(
        self, authenticated_client, active_user, settings, sphere
    ):
        settings.TLDRAW_LICENSE_KEY = "tldraw-key"
        board = BoardFactory(sphere=sphere)

        response = authenticated_client.get(_url(board.share_code))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/board.html",
            context_data={
                "board": board_dto(board),
                "is_owner": False,
                "license_key": "tldraw-key",
            },
        )
        assert BoardVisit.objects.filter(board=board, user=active_user).exists()

    def test_creator_is_owner(self, authenticated_client, active_user, sphere):
        board = BoardFactory(sphere=sphere, creator=active_user)

        response = authenticated_client.get(_url(board.share_code))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/board.html",
            context_data={
                "board": board_dto(board),
                "is_owner": True,
                "license_key": "",
            },
        )

    def test_unknown_code(self, client):
        assert_response_404(client.get(_url("missing")))

    def test_board_of_another_sphere_leaves_no_visit(self, authenticated_client):
        board = BoardFactory(sphere=SphereFactory())

        response = authenticated_client.get(_url(board.share_code))

        assert_response_404(response)
        assert not BoardVisit.objects.exists()

    def test_feature_unavailable(self, client, board_settings, sphere):
        board_settings.BOARD_HOST = ""
        board = BoardFactory(sphere=sphere)

        assert_response_404(client.get(_url(board.share_code)))
