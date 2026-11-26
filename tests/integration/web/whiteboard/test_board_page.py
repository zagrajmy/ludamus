from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import BoardVisit
from tests.integration.conftest import BoardFactory, SphereFactory
from tests.integration.utils import assert_response, assert_response_404


def _url(share_code):
    return reverse("web:boards:board", kwargs={"share_code": share_code})


class TestBoardPageView:
    def test_old_address_sends_a_guest_to_the_board_app(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        response = client.get(_url(board.share_code))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"http://localhost:8788/b/{board.share_code}?lang=en",
        )
        # NOTE: the board joins a member's list when the board app asks for
        # a pass, not on the way through.
        assert not BoardVisit.objects.exists()

    @pytest.mark.usefixtures("polish_catalog")
    def test_board_app_opens_in_the_language_of_the_site(
        self, authenticated_client, sphere
    ):
        board = BoardFactory(sphere=sphere)

        response = authenticated_client.get(
            _url(board.share_code), headers={"accept-language": "pl"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"http://localhost:8788/b/{board.share_code}?lang=pl",
        )

    def test_deployed_board_app_is_reached_over_tls(
        self, client, board_settings, sphere
    ):
        board_settings.BOARD_HOST = "board.example.com"
        board = BoardFactory(sphere=sphere)

        response = client.get(_url(board.share_code))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"https://board.example.com/b/{board.share_code}?lang=en",
        )

    def test_unknown_code(self, client):
        assert_response_404(client.get(_url("missing")))

    def test_board_of_another_sphere(self, authenticated_client):
        board = BoardFactory(sphere=SphereFactory())

        response = authenticated_client.get(_url(board.share_code))

        assert_response_404(response)

    def test_feature_unavailable(self, client, board_settings, sphere):
        board_settings.BOARD_HOST = ""
        board = BoardFactory(sphere=sphere)

        assert_response_404(client.get(_url(board.share_code)))
