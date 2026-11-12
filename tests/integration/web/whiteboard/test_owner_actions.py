from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib.messages import constants
from django.urls import reverse
from django.utils import formats
from django.utils.timezone import localdate

from ludamus.links.db.django.models import Board
from tests.integration.conftest import BoardFactory, SphereFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.whiteboard.helpers import board_dto, verified_claims

INDEX = reverse("web:boards:index")
# About 71 bits out of letters and digits.
SHARE_CODE_LENGTH = 12


class TestBoardCreateActionView:
    URL = reverse("web:boards:create")

    def test_guest_cannot_create(self, client):
        response = client.post(self.URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.URL}"
        )
        assert not Board.objects.exists()

    def test_creates_a_dated_board_and_opens_it(
        self, authenticated_client, active_user, sphere
    ):
        response = authenticated_client.post(self.URL)

        board = Board.objects.get()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:boards:board", kwargs={"share_code": board.share_code}),
        )
        today = formats.date_format(localdate(), "MONTH_DAY_FORMAT")
        assert (board.sphere_id, board.creator_id, board.title) == (
            sphere.pk,
            active_user.pk,
            f"Board {today}",
        )
        assert len(board.share_code) == SHARE_CODE_LENGTH

    def test_requires_post(self, authenticated_client):
        assert_response(
            authenticated_client.get(self.URL), HTTPStatus.METHOD_NOT_ALLOWED
        )

    def test_feature_unavailable(self, authenticated_client, board_settings):
        board_settings.BOARD_HOST = ""

        assert_response_404(authenticated_client.post(self.URL))
        assert not Board.objects.exists()


class TestBoardEditPageView:
    def _url(self, board):
        return reverse("web:boards:edit", kwargs={"pk": board.pk})

    def test_renames(self, authenticated_client, active_user, sphere):
        board = BoardFactory(sphere=sphere, creator=active_user)

        response = authenticated_client.post(
            self._url(board), {"title": "  Mothership  "}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=INDEX,
            messages=[(constants.SUCCESS, "Board renamed.")],
        )
        board.refresh_from_db()
        assert board.title == "Mothership"

    def test_empty_name_is_refused(self, authenticated_client, active_user, sphere):
        board = BoardFactory(sphere=sphere, creator=active_user, title="Before")

        response = authenticated_client.post(self._url(board), {"title": "   "})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="whiteboard/edit.html",
            context_data={"board": board_dto(board), "form": ANY},
        )
        assert response.context_data["form"].errors == {
            "title": ["This field is required."]
        }
        board.refresh_from_db()
        assert board.title == "Before"

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_not_the_creator(self, authenticated_client, sphere, method):
        board = BoardFactory(sphere=sphere, title="Before")

        response = getattr(authenticated_client, method)(
            self._url(board), {"title": "Hijacked"}
        )

        assert_response_404(response)
        board.refresh_from_db()
        assert board.title == "Before"

    def test_own_board_in_another_sphere(self, authenticated_client, active_user):
        board = BoardFactory(sphere=SphereFactory(), creator=active_user, title="B")

        response = authenticated_client.post(self._url(board), {"title": "Moved"})

        assert_response_404(response)
        board.refresh_from_db()
        assert board.title == "B"


class TestBoardResetLinkActionView:
    def _url(self, board):
        return reverse("web:boards:reset-link", kwargs={"pk": board.pk})

    def test_new_code_new_version_and_the_old_link_is_dead(
        self, authenticated_client, active_user, sphere
    ):
        board = BoardFactory(sphere=sphere, creator=active_user)
        old_code = board.share_code

        response = authenticated_client.post(self._url(board))

        reset = [
            (
                constants.SUCCESS,
                "The board has a new link. The old one no longer opens it.",
            )
        ]
        assert_response(response, HTTPStatus.FOUND, url=INDEX, messages=reset)
        board.refresh_from_db()
        assert board.share_code != old_code
        assert board.link_version == 1
        # NOTE: the 404 page shows no toasts, so the message is still queued.
        assert_response_404(
            authenticated_client.get(
                reverse("web:boards:board", kwargs={"share_code": old_code})
            ),
            messages=reset,
        )
        bootstrap = authenticated_client.post(
            reverse("web:boards:bootstrap", kwargs={"share_code": board.share_code})
        )
        assert verified_claims(bootstrap.json()["pass"])["link"] == 1

    def test_not_the_creator(self, authenticated_client, sphere):
        board = BoardFactory(sphere=sphere)
        old_code = board.share_code

        assert_response_404(authenticated_client.post(self._url(board)))
        board.refresh_from_db()
        assert (board.share_code, board.link_version) == (old_code, 0)

    def test_guest_is_sent_to_sign_in(self, client, sphere):
        board = BoardFactory(sphere=sphere)
        url = self._url(board)

        assert_response(
            client.post(url), HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )


class TestBoardDeleteActionView:
    def _url(self, board):
        return reverse("web:boards:delete", kwargs={"pk": board.pk})

    def test_deletes(self, authenticated_client, active_user, sphere):
        board = BoardFactory(sphere=sphere, creator=active_user)

        response = authenticated_client.post(self._url(board))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=INDEX,
            messages=[(constants.SUCCESS, "Board deleted.")],
        )
        assert not Board.objects.filter(pk=board.pk).exists()

    def test_not_the_creator(self, authenticated_client, sphere):
        board = BoardFactory(sphere=sphere)

        assert_response_404(authenticated_client.post(self._url(board)))
        assert Board.objects.filter(pk=board.pk).exists()

    def test_own_board_in_another_sphere(self, authenticated_client, active_user):
        board = BoardFactory(sphere=SphereFactory(), creator=active_user)

        assert_response_404(authenticated_client.post(self._url(board)))
        assert Board.objects.filter(pk=board.pk).exists()
