import base64
import hashlib
from unittest.mock import MagicMock

import pytest

from ludamus.mills.mcp import AUTHORIZATION_CODE_TTL_SECONDS, McpAuthorizationService
from ludamus.pacts.mcp import (
    McpClientDTO,
    McpClientRejectedError,
    McpGrantDTO,
    McpGrantRejectedError,
    ToolScope,
)

CLIENT_ID = "https://client.example/oauth/metadata.json"
LOOPBACK_REDIRECT = "http://127.0.0.1/callback"
VERIFIER = "v" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
    .rstrip(b"=")
    .decode()
)


def _document(**overrides):
    return {
        "client_id": CLIENT_ID,
        "client_name": "Example Agent",
        "redirect_uris": [LOOPBACK_REDIRECT, "https://client.example/callback"],
    } | overrides


def _service(document=None, stored=None):
    fetcher = MagicMock()
    fetcher.fetch.return_value = _document() if document is None else document
    codes = MagicMock()
    codes.take.return_value = stored
    return McpAuthorizationService(fetcher=fetcher, codes=codes), fetcher, codes


def _stored(**overrides):
    return {
        "client_id": CLIENT_ID,
        "redirect_uri": LOOPBACK_REDIRECT,
        "code_challenge": CHALLENGE,
        "user_id": 7,
        "scope": ToolScope.ORGANIZER,
        "sphere_id": 3,
        "event_id": 11,
    } | overrides


class TestResolveClient:
    def test_returns_client_for_listed_redirect(self):
        service, fetcher, _codes = _service()

        client = service.resolve_client(
            client_id=CLIENT_ID, redirect_uri="https://client.example/callback"
        )

        assert client == McpClientDTO(
            client_id=CLIENT_ID,
            client_name="Example Agent",
            client_host="client.example",
            redirect_uri="https://client.example/callback",
        )
        fetcher.fetch.assert_called_once_with(CLIENT_ID)

    def test_loopback_redirect_matches_on_any_port(self):
        service, _fetcher, _codes = _service()

        client = service.resolve_client(
            client_id=CLIENT_ID, redirect_uri="http://127.0.0.1:49152/callback"
        )

        assert client.redirect_uri == "http://127.0.0.1:49152/callback"

    def test_name_falls_back_to_host_and_is_capped(self):
        service, _fetcher, _codes = _service(_document(client_name="  "))
        long_service, _f, _c = _service(_document(client_name="x" * 300))

        unnamed = service.resolve_client(
            client_id=CLIENT_ID, redirect_uri=LOOPBACK_REDIRECT
        )
        long_named = long_service.resolve_client(
            client_id=CLIENT_ID, redirect_uri=LOOPBACK_REDIRECT
        )

        assert unnamed.client_name == "client.example"
        assert long_named.client_name == "x" * 100

    @pytest.mark.parametrize(
        "client_id",
        (
            "http://client.example/metadata.json",
            "https://client.example",
            "https://client.example/",
            "https://user:pw@client.example/metadata.json",
            "https://client.example/metadata.json#frag",
            "https://client.example/a/../metadata.json",
            "not a url",
        ),
    )
    def test_rejects_malformed_client_id_without_fetching(self, client_id):
        service, fetcher, _codes = _service()

        with pytest.raises(McpClientRejectedError):
            service.resolve_client(client_id=client_id, redirect_uri=LOOPBACK_REDIRECT)

        fetcher.fetch.assert_not_called()

    @pytest.mark.parametrize(
        ("document", "reason"),
        (
            (_document(client_id="https://other.example/m.json"), "different"),
            (_document(token_endpoint_auth_method="private_key_jwt"), "public"),
            (_document(redirect_uris=[]), "redirect_uris"),
            ({"client_id": CLIENT_ID}, "redirect_uris"),
        ),
    )
    def test_rejects_unusable_document(self, document, reason):
        service, _fetcher, _codes = _service(document)

        with pytest.raises(McpClientRejectedError, match=reason):
            service.resolve_client(client_id=CLIENT_ID, redirect_uri=LOOPBACK_REDIRECT)

    @pytest.mark.parametrize(
        "redirect_uri",
        (
            "https://evil.example/callback",
            "http://127.0.0.1:5000/other",
            "http://localhost/callback",
            "javascript:alert(1)",
            "https://client.example/callback#x",
            "http://client.example/callback",
            "",
        ),
    )
    def test_rejects_redirect_uri(self, redirect_uri):
        document = _document(
            redirect_uris=[
                LOOPBACK_REDIRECT,
                "https://client.example/callback",
                "http://client.example/callback",
                "javascript:alert(1)",
            ]
        )
        service, _fetcher, _codes = _service(document)

        with pytest.raises(McpClientRejectedError):
            service.resolve_client(client_id=CLIENT_ID, redirect_uri=redirect_uri)


class TestIssueCode:
    def test_stores_grant_under_fresh_code(self):
        service, _fetcher, codes = _service()
        data = _stored()

        code = service.issue_code(data)

        codes.put.assert_called_once_with(
            code, data, ttl_seconds=AUTHORIZATION_CODE_TTL_SECONDS
        )


class TestRedeemCode:
    def test_returns_grant(self):
        service, _fetcher, codes = _service(stored=_stored())

        grant = service.redeem_code(
            code="abc",
            client_id=CLIENT_ID,
            redirect_uri=LOOPBACK_REDIRECT,
            code_verifier=VERIFIER,
        )

        assert grant == McpGrantDTO(
            client_id=CLIENT_ID,
            user_id=7,
            scope=ToolScope.ORGANIZER,
            sphere_id=3,
            event_id=11,
        )
        codes.take.assert_called_once_with("abc")

    def test_unknown_code(self):
        service, _fetcher, _codes = _service(stored=None)

        with pytest.raises(McpGrantRejectedError, match="invalid"):
            service.redeem_code(
                code="abc",
                client_id=CLIENT_ID,
                redirect_uri=LOOPBACK_REDIRECT,
                code_verifier=VERIFIER,
            )

    @pytest.mark.parametrize(
        ("client_id", "redirect_uri"),
        (
            ("https://other.example/m.json", LOOPBACK_REDIRECT),
            (CLIENT_ID, "http://127.0.0.1:9/callback"),
        ),
    )
    def test_code_bound_to_client(self, client_id, redirect_uri):
        service, _fetcher, _codes = _service(stored=_stored())

        with pytest.raises(McpGrantRejectedError, match="different client"):
            service.redeem_code(
                code="abc",
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_verifier=VERIFIER,
            )

    @pytest.mark.parametrize("verifier", ("w" * 43, "short", "v" * 42 + "!"))
    def test_wrong_verifier(self, verifier):
        service, _fetcher, _codes = _service(stored=_stored())

        with pytest.raises(McpGrantRejectedError, match="code_verifier"):
            service.redeem_code(
                code="abc",
                client_id=CLIENT_ID,
                redirect_uri=LOOPBACK_REDIRECT,
                code_verifier=verifier,
            )
