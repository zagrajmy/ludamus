from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import BoardVisit
from ludamus.pacts.board import BoardListItemDTO
from tests.integration.conftest import BoardFactory, SphereFactory
from tests.integration.utils import assert_response, assert_response_404

URL = reverse("web:boards:index")


def _item(board, *, is_owner, opened_at):
    return BoardListItemDTO(
        pk=board.pk,
        title=board.title,
        share_code=board.share_code,
        is_owner=is_owner,
        last_opened_at=opened_at,
    )


class TestBoardsPageView:
    def test_login_required(self, client):
        assert_response(
            client.get(URL), HTTPStatus.FOUND, url=f"/crowd/login-required/?next={URL}"
        )

    def test_lists_created_and_visited_boards_only(
        self, authenticated_client, active_user, sphere
    ):
        created = BoardFactory(sphere=sphere, creator=active_user)
        visited = BoardFactory(sphere=sphere)
        opened_at = datetime.now(UTC) + timedelta(minutes=1)
        BoardVisit.objects.create(
            board=visited, user=active_user, last_opened_at=opened_at
        )
        BoardFactory(sphere=sphere)
        foreign = BoardFactory(sphere=SphereFactory(), creator=active_user)
        BoardVisit.objects.create(
            board=foreign, user=active_user, last_opened_at=opened_at
        )

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/index.html",
            context_data={
                "boards": [
                    _item(visited, is_owner=False, opened_at=opened_at),
                    _item(created, is_owner=True, opened_at=created.creation_time),
                ]
            },
        )

    def test_no_boards_yet(self, authenticated_client, sphere):
        BoardFactory(sphere=sphere)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/index.html",
            context_data={"boards": []},
        )

    def test_unavailable_without_a_signing_key(self, authenticated_client, settings):
        settings.PARLEY_SIGNING_PRIVATE_KEY = ""

        assert_response_404(authenticated_client.get(URL))

    def test_unavailable_without_a_worker(self, client, board_settings):
        # NOTE: the 404 comes before the login redirect, which would leak
        # that the page exists.
        board_settings.BOARD_HOST = ""

        assert_response_404(client.get(URL))
