import socket

import pytest
from urllib3.exceptions import NewConnectionError

from ludamus.links.cache import CacheAuthorizationCodeStore
from ludamus.links.client_metadata import MAX_DOCUMENT_BYTES, HttpClientMetadataFetcher
from ludamus.pacts.mcp import (
    ClientRejection,
    MaintainerGrant,
    McpClientRejectedError,
    McpIssuedCode,
)
from tests.integration.cimd import PUBLIC_ADDRESS, FetchRecord, install

URL = "https://client.example/oauth/metadata.json"
PATH = "/oauth/metadata.json"
DOCUMENT = {"client_id": URL, "redirect_uris": ["http://127.0.0.1/cb"]}


@pytest.fixture(name="server")
def server_fixture(monkeypatch):
    return install(monkeypatch)


def _rejection(url=URL):
    with pytest.raises(McpClientRejectedError) as caught:
        HttpClientMetadataFetcher.fetch(url)
    return caught.value.reason


class TestHttpClientMetadataFetcher:
    def test_fetches_from_the_vetted_address_with_the_real_hostname(self, server):
        server.serve(f"{PATH}?v=2", document=DOCUMENT)

        document = HttpClientMetadataFetcher.fetch(f"{URL}?v=2")

        assert document == DOCUMENT
        assert server.fetches == [
            FetchRecord(
                address=PUBLIC_ADDRESS,
                port=443,
                path=f"{PATH}?v=2",
                headers={"Host": "client.example", "Accept": "application/json"},
                server_hostname="client.example",
            )
        ]

    @pytest.mark.parametrize(
        ("route", "reason"),
        (
            ({"status": 404, "body": b"nope"}, ClientRejection.UNREACHABLE),
            ({"status": 302, "body": b""}, ClientRejection.UNREACHABLE),
            (
                {"body": b"x" * (MAX_DOCUMENT_BYTES + 1)},
                ClientRejection.INVALID_DOCUMENT,
            ),
            ({"body": b"{not json"}, ClientRejection.INVALID_DOCUMENT),
            ({"body": b'["a"]'}, ClientRejection.INVALID_DOCUMENT),
            (
                {"document": {"redirect_uris": "http://x/"}},
                ClientRejection.INVALID_DOCUMENT,
            ),
            (
                {"error": NewConnectionError(None, "refused")},
                ClientRejection.UNREACHABLE,
            ),
        ),
    )
    def test_rejects_bad_answers(self, server, route, reason):
        server.serve(PATH, **route)

        assert _rejection() == reason

    def test_slow_trickle_hits_the_deadline(self, server, monkeypatch):
        server.serve(PATH, body=b" " * 3000)
        ticks = iter([0.0, 1.0, 99.0, 99.0, 99.0])
        monkeypatch.setattr(
            "ludamus.links.client_metadata.time.monotonic", lambda: next(ticks)
        )

        assert _rejection() == ClientRejection.UNREACHABLE


class TestPublicHostGuard:
    @pytest.mark.parametrize(
        "addresses",
        (
            ("127.0.0.1",),
            ("10.1.2.3",),
            ("169.254.169.254",),
            ("93.184.216.34", "192.168.0.1"),
            ("fe80::1%eth0",),
        ),
    )
    def test_refuses_non_public_hosts_without_connecting(self, monkeypatch, addresses):
        server = install(monkeypatch, *addresses)

        assert _rejection() == ClientRejection.NOT_PUBLIC
        assert not server.fetches

    def test_refuses_unresolvable_host(self, monkeypatch):
        server = install(monkeypatch)

        def fail(host, _port, **_kwargs):
            raise socket.gaierror(host)

        monkeypatch.setattr(socket, "getaddrinfo", fail)

        assert _rejection() == ClientRejection.UNREACHABLE
        assert not server.fetches


class TestCacheAuthorizationCodeStore:
    def test_code_redeems_once(self):
        issued = McpIssuedCode(
            client_id=URL,
            redirect_uri="http://127.0.0.1/cb",
            code_challenge="c",
            grant=MaintainerGrant(user_id=1),
        )
        CacheAuthorizationCodeStore.put("code-1", issued, ttl_seconds=60)

        assert CacheAuthorizationCodeStore.take("code-1") == issued
        assert CacheAuthorizationCodeStore.take("code-1") is None
        assert CacheAuthorizationCodeStore.take("never-issued") is None
