import json
import time
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from ludamus.gates.web.django.whiteboard.copy import board_copy
from tests.integration.conftest import BoardFactory, SphereFactory, UserFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.whiteboard.helpers import verified_claims


def _url(board):
    return reverse("web:boards:bootstrap", kwargs={"share_code": board.share_code})


def _post(client, board, body=None):
    return client.post(
        _url(board),
        data=json.dumps(body) if body is not None else "",
        content_type="application/json",
    )


class TestMember:
    def test_creator_gets_an_owner_pass_for_the_board(
        self, authenticated_client, active_user, sphere
    ):
        board = BoardFactory(sphere=sphere, creator=active_user, link_version=2)

        before = int(time.time())
        response = _post(authenticated_client, board)

        assert_response(response, HTTPStatus.OK)
        payload = response.json()
        claims = verified_claims(payload.pop("pass"))
        assert payload == {
            "socketUrl": f"ws://localhost:8788/rooms/{board.pk}",
            "httpUrl": f"http://localhost:8788/rooms/{board.pk}",
            "person": {"id": f"u:{active_user.pk}", "name": "Test User", "owner": True},
            "title": board.title,
            "copy": board_copy(),
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

    def test_long_account_name_is_cut_to_what_the_worker_takes(self, client, sphere):
        user = UserFactory(name="A" * 60)
        client.force_login(user)
        board = BoardFactory(sphere=sphere)

        response = _post(client, board)

        assert_response(response, HTTPStatus.OK)
        assert response.json()["person"]["name"] == "A" * 40

    def test_deployed_worker_is_reached_over_tls(
        self, authenticated_client, board_settings, sphere
    ):
        board_settings.BOARD_HOST = "board.example.com"
        board = BoardFactory(sphere=sphere)

        response = _post(authenticated_client, board)

        assert_response(response, HTTPStatus.OK)
        payload = response.json()
        assert payload["socketUrl"] == f"wss://board.example.com/rooms/{board.pk}"
        assert payload["httpUrl"] == f"https://board.example.com/rooms/{board.pk}"


class TestGuest:
    def test_without_a_name_is_asked_for_one(self, client, sphere):
        board = BoardFactory(sphere=sphere)

        response = _post(client, board)

        assert_response(
            response, HTTPStatus.UNPROCESSABLE_ENTITY, json={"error": "name-required"}
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
        claims = verified_claims(second.json()["pass"])
        assert (claims["sub"], claims["name"], claims["owner"]) == (
            person["id"],
            "Ania",
            False,
        )

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

        response = client.post(_url(board), data=body, content_type="application/json")

        assert_response(
            response, HTTPStatus.BAD_REQUEST, json={"error": "invalid-request"}
        )


class TestRefusals:
    def test_unknown_code(self, client):
        response = client.post(
            reverse("web:boards:bootstrap", kwargs={"share_code": "nope"}),
            content_type="application/json",
        )

        assert_response(response, HTTPStatus.NOT_FOUND, json={"error": "not-found"})

    def test_board_of_another_sphere(self, authenticated_client):
        board = BoardFactory(sphere=SphereFactory())

        response = _post(authenticated_client, board)

        assert_response(response, HTTPStatus.NOT_FOUND, json={"error": "not-found"})

    def test_feature_unavailable(self, authenticated_client, board_settings, sphere):
        board_settings.BOARD_HOST = ""
        board = BoardFactory(sphere=sphere)

        response = _post(authenticated_client, board)

        assert_response_404(response)

    def test_get_is_not_allowed(self, authenticated_client, sphere):
        board = BoardFactory(sphere=sphere)

        response = authenticated_client.get(_url(board))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_csrf_token_is_required(self, sphere):
        board = BoardFactory(sphere=sphere)
        client = Client(enforce_csrf_checks=True)

        response = _post(client, board, {"name": "Ania"})

        assert_response(response, HTTPStatus.FORBIDDEN)

    def test_one_address_is_throttled(self, client, sphere):
        board = BoardFactory(sphere=sphere)
        for _ in range(30):
            _post(client, board, {"name": "Ania"})

        response = _post(client, board)

        assert_response(
            response, HTTPStatus.TOO_MANY_REQUESTS, json={"error": "too-many-requests"}
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
