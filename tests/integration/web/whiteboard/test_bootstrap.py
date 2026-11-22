import json
import time
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from ludamus.links.db.django.models import Board, BoardVisit
from tests.integration.conftest import BoardFactory, SphereFactory, UserFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.whiteboard.helpers import verified_claims

BOARD_APP = "http://localhost:8788"
# What the board app's origin gets back with every answer, and nobody else.
ANSWERS_BOARD_APP = {
    "Access-Control-Allow-Origin": BOARD_APP,
    "Access-Control-Allow-Credentials": "true",
}
ANSWERS_NOBODY = {
    "Access-Control-Allow-Origin": None,
    "Access-Control-Allow-Credentials": None,
}


def _url(board):
    return reverse("web:boards:bootstrap", kwargs={"share_code": board.share_code})


def _post(client, board, body=None, *, origin=BOARD_APP, content_type=None):
    return client.post(
        _url(board),
        # NOTE: the board app always sends a JSON object, `{}` when it names
        # nobody; the test client drops the content type of an empty body.
        data=json.dumps(body if body is not None else {}),
        content_type=content_type or "application/json",
        headers={} if origin is None else {"origin": origin},
    )


class TestMember:
    def test_creator_gets_an_owner_pass_for_the_board(
        self, authenticated_client, active_user, sphere
    ):
        board = BoardFactory(sphere=sphere, creator=active_user, link_version=2)

        before = int(time.time())
        response = _post(authenticated_client, board)

        assert_response(response, HTTPStatus.OK, headers=ANSWERS_BOARD_APP)
        assert "Origin" in response["Vary"]
        payload = response.json()
        claims = verified_claims(payload.pop("pass"))
        assert payload == {
            "board": str(board.pk),
            "person": {"id": f"u:{active_user.pk}", "name": "Test User", "owner": True},
            "title": board.title,
            "sphere": {"name": sphere.name, "url": "http://testserver/"},
            "boardsUrl": "http://testserver/boards/",
        }
        issued_at = claims.pop("iat")
        assert before <= issued_at <= int(time.time())
        assert claims == {
            "iss": "ludamus",
            # NOTE: a Parley pass says "parley"; the Worker checks for this.
            "aud": "board",
            "sub": f"u:{active_user.pk}",
            "board": str(board.pk),
            "link": 2,
            "name": "Test User",
            "owner": True,
            "exp": issued_at + 5 * 60,
        }

    def test_someone_else_is_not_owner_and_body_name_is_ignored(
        self, authenticated_client, active_user, sphere
    ):
        board = BoardFactory(sphere=sphere)

        response = _post(authenticated_client, board, {"name": "Impostor"})

        assert_response(response, HTTPStatus.OK)
        assert response.json()["person"] == {
            "id": f"u:{active_user.pk}",
            "name": "Test User",
            "owner": False,
        }

    def test_the_pass_puts_the_board_on_their_list(
        self, authenticated_client, active_user, sphere
    ):
        board = BoardFactory(sphere=sphere)

        _post(authenticated_client, board)

        assert BoardVisit.objects.filter(board=board, user=active_user).exists()

    def test_a_board_of_another_sphere_opens_by_its_link(
        self, authenticated_client, active_user
    ):
        # NOTE: the board app asks the root domain whatever sphere the board
        # is on; the share code is what opens a board.
        other = SphereFactory(site__domain="kapitularz.testserver")
        board = BoardFactory(sphere=other)

        response = _post(authenticated_client, board)

        assert_response(response, HTTPStatus.OK)
        assert (response.json()["sphere"], response.json()["boardsUrl"]) == (
            {"name": other.name, "url": "http://kapitularz.testserver/"},
            "http://kapitularz.testserver/boards/",
        )
        assert BoardVisit.objects.filter(board=board, user=active_user).exists()

    def test_long_account_name_is_cut_to_what_the_worker_takes(self, client, sphere):
        user = UserFactory(name="A" * 60)
        client.force_login(user)
        board = BoardFactory(sphere=sphere)

        response = _post(client, board)

        assert_response(response, HTTPStatus.OK)
        assert response.json()["person"]["name"] == "A" * 40


class TestGuest:
    def test_without_a_name_is_asked_for_one(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        response = _post(client, board)

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "name-required"},
            headers=ANSWERS_BOARD_APP,
        )

    def test_name_is_remembered_and_the_id_stays_the_same(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        first = _post(client, board, {"name": "  Ania  "})
        second = _post(client, board)

        assert_response(first, HTTPStatus.OK)
        assert_response(second, HTTPStatus.OK)
        person = first.json()["person"]
        assert person["id"].startswith("g:")
        assert person == {"id": person["id"], "name": "Ania", "owner": False}
        assert second.json()["person"] == person
        assert (first.json()["sphere"], first.json()["boardsUrl"]) == (
            {"name": sphere.name, "url": "http://testserver/"},
            None,
        )
        claims = verified_claims(second.json()["pass"])
        assert (claims["sub"], claims["name"], claims["owner"]) == (
            person["id"],
            "Ania",
            False,
        )
        assert not BoardVisit.objects.exists()

    def test_a_new_name_replaces_the_remembered_one(self, client, sphere):
        board = BoardFactory(sphere=sphere)
        first = _post(client, board, {"name": "Ania"})

        renamed = _post(client, board, {"name": "Ola"})

        assert_response(renamed, HTTPStatus.OK)
        assert renamed.json()["person"] == {
            "id": first.json()["person"]["id"],
            "name": "Ola",
            "owner": False,
        }

    @pytest.mark.parametrize("name", ("", "   ", "x" * 41, "Ania\u0000"))
    def test_unusable_name_is_refused(self, client, sphere, name):
        board = BoardFactory(sphere=sphere)

        response = _post(client, board, {"name": name})

        assert_response(
            response, HTTPStatus.UNPROCESSABLE_ENTITY, json={"error": "name-invalid"}
        )

    @pytest.mark.parametrize("body", ("[]", '{"name": 7}', "not json"))
    def test_malformed_body_is_a_bad_request(self, client, sphere, body):
        board = BoardFactory(sphere=sphere)

        response = client.post(
            _url(board),
            data=body,
            content_type="application/json",
            headers={"origin": BOARD_APP},
        )

        assert_response(
            response, HTTPStatus.BAD_REQUEST, json={"error": "invalid-request"}
        )


class TestCrossOrigin:
    def test_board_app_preflight_is_answered(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        response = client.options(
            _url(board),
            headers={
                "origin": BOARD_APP,
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type",
            },
        )

        assert_response(
            response,
            HTTPStatus.NO_CONTENT,
            headers=ANSWERS_BOARD_APP | {
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    @pytest.mark.parametrize(
        "origin",
        (
            "https://evil.example",
            # The site itself: no Django page asks for board passes.
            "http://testserver",
            # The board's host over another scheme or port is another origin.
            "https://localhost:8788",
            "http://localhost:8789",
            "http://localhost:8788.evil.example",
            # Sandboxed frames and file pages send this.
            "null",
        ),
    )
    def test_preflight_from_another_origin_is_refused(self, client, sphere, origin):
        board = BoardFactory(sphere=sphere)

        response = client.options(
            _url(board),
            headers={"origin": origin, "access-control-request-method": "POST"},
        )

        assert_response(
            response,
            HTTPStatus.FORBIDDEN,
            json={"error": "forbidden-origin"},
            headers=ANSWERS_NOBODY,
        )

    @pytest.mark.parametrize(
        "origin", ("https://evil.example", "http://testserver", "null", None)
    )
    def test_member_pass_is_refused_to_another_origin_without_a_trace(
        self, authenticated_client, sphere, origin
    ):
        board = BoardFactory(sphere=sphere)

        response = _post(authenticated_client, board, origin=origin)

        assert_response(
            response,
            HTTPStatus.FORBIDDEN,
            json={"error": "forbidden-origin"},
            headers=ANSWERS_NOBODY,
        )
        assert not BoardVisit.objects.exists()

    def test_guest_name_from_another_origin_is_not_remembered(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        refused = _post(client, board, {"name": "Mallory"}, origin="https://evil.ex")
        mine = _post(client, board)

        assert_response(refused, HTTPStatus.FORBIDDEN, headers=ANSWERS_NOBODY)
        assert_response(
            mine, HTTPStatus.UNPROCESSABLE_ENTITY, json={"error": "name-required"}
        )

    @pytest.mark.parametrize(
        "content_type",
        ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"),
    )
    def test_body_a_form_could_send_is_refused(self, client, sphere, content_type):
        # NOTE: these three need no preflight, so a page anywhere could send
        # them with the visitor's cookie; only JSON gets through.
        board = BoardFactory(sphere=sphere)

        response = client.post(
            _url(board),
            data='{"name": "Ania"}',
            content_type=content_type,
            headers={"origin": BOARD_APP},
        )

        assert_response(
            response,
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            json={"error": "invalid-request"},
            headers=ANSWERS_BOARD_APP,
        )

    def test_board_app_needs_no_csrf_token(self, sphere):
        board = BoardFactory(sphere=sphere)
        client = Client(enforce_csrf_checks=True)

        response = _post(client, board, {"name": "Ania"})

        assert_response(response, HTTPStatus.OK)

    def test_csrf_still_guards_every_other_board_action(self, active_user, sphere):
        client = Client(enforce_csrf_checks=True)
        client.force_login(active_user)

        response = client.post(
            reverse("web:boards:create"), headers={"origin": BOARD_APP}
        )

        assert_response(response, HTTPStatus.FORBIDDEN)
        assert not Board.objects.exists()

    def test_deployed_board_app_origin_is_https(
        self, authenticated_client, board_settings, sphere
    ):
        board_settings.BOARD_HOST = "board.example.com"
        board = BoardFactory(sphere=sphere)

        plain = _post(authenticated_client, board, origin="http://board.example.com")
        tls = _post(authenticated_client, board, origin="https://board.example.com")

        assert_response(plain, HTTPStatus.FORBIDDEN, headers=ANSWERS_NOBODY)
        assert_response(
            tls,
            HTTPStatus.OK,
            headers={"Access-Control-Allow-Origin": "https://board.example.com"},
        )


class TestRefusals:
    def test_unknown_code(self, client):
        response = client.post(
            reverse("web:boards:bootstrap", kwargs={"share_code": "nope"}),
            data="{}",
            content_type="application/json",
            headers={"origin": BOARD_APP},
        )

        assert_response(
            response,
            HTTPStatus.NOT_FOUND,
            json={"error": "not-found"},
            headers=ANSWERS_BOARD_APP,
        )

    def test_feature_unavailable(self, authenticated_client, board_settings, sphere):
        board_settings.BOARD_HOST = ""
        board = BoardFactory(sphere=sphere)

        response = _post(authenticated_client, board)

        assert_response_404(response)

    def test_get_is_not_allowed(self, authenticated_client, sphere):
        board = BoardFactory(sphere=sphere)

        response = authenticated_client.get(_url(board), headers={"origin": BOARD_APP})

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_one_address_is_throttled(self, client, sphere):
        board = BoardFactory(sphere=sphere)
        for _ in range(30):
            _post(client, board, {"name": "Ania"})

        response = _post(client, board)

        assert_response(
            response,
            HTTPStatus.TOO_MANY_REQUESTS,
            json={"error": "too-many-requests"},
            headers=ANSWERS_BOARD_APP,
        )

    def test_answers_are_never_cached(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        response = _post(client, board, {"name": "Ania"})

        assert_response(
            response,
            HTTPStatus.OK,
            cache_control={
                "max-age=0",
                "no-cache",
                "no-store",
                "must-revalidate",
                "private",
            },
        )
