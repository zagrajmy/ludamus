import json
import socket

import pytest
import requests
import responses

from ludamus.links.cache import CacheAuthorizationCodeStore
from ludamus.links.client_metadata import MAX_DOCUMENT_BYTES, HttpClientMetadataFetcher
from ludamus.pacts.mcp import McpClientRejectedError, ToolScope

URL = "https://client.example/oauth/metadata.json"


def _resolves_to(*addresses):
    def resolve(_host, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]

    return resolve


@pytest.fixture(name="public_dns")
def public_dns_fixture(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolves_to("93.184.216.34"))


@pytest.mark.usefixtures("public_dns")
class TestHttpClientMetadataFetcher:
    @responses.activate
    def test_returns_document(self):
        document = {"client_id": URL, "redirect_uris": ["http://127.0.0.1/cb"]}
        responses.get(URL, json=document)

        assert HttpClientMetadataFetcher().fetch(URL) == document

    @responses.activate
    @pytest.mark.parametrize(
        ("kwargs", "reason"),
        (
            ({"status": 404}, "HTTP 404"),
            ({"status": 302, "headers": {"Location": "http://10.0.0.1/"}}, "HTTP 302"),
            ({"body": "x" * (MAX_DOCUMENT_BYTES + 1)}, "larger than 5 KB"),
            ({"body": "{not json"}, "not valid client metadata"),
            ({"body": json.dumps(["a"])}, "not valid client metadata"),
            ({"json": {"redirect_uris": "http://x/"}}, "not valid client metadata"),
            ({"body": requests.ConnectionError("down")}, "could not be fetched"),
        ),
    )
    def test_rejects_bad_answers(self, kwargs, reason):
        responses.get(URL, **kwargs)

        with pytest.raises(McpClientRejectedError, match=reason):
            HttpClientMetadataFetcher().fetch(URL)


class TestPublicHostGuard:
    @responses.activate
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
        monkeypatch.setattr(socket, "getaddrinfo", _resolves_to(*addresses))

        with pytest.raises(McpClientRejectedError, match="not a public address"):
            HttpClientMetadataFetcher().fetch(URL)

        assert len(responses.calls) == 0

    def test_refuses_unresolvable_host(self, monkeypatch):
        def fail(host, _port):
            raise socket.gaierror(host)

        monkeypatch.setattr(socket, "getaddrinfo", fail)

        with pytest.raises(McpClientRejectedError, match="does not resolve"):
            HttpClientMetadataFetcher().fetch(URL)


class TestCacheAuthorizationCodeStore:
    def test_code_redeems_once(self):
        store = CacheAuthorizationCodeStore()
        data = {
            "client_id": URL,
            "redirect_uri": "http://127.0.0.1/cb",
            "code_challenge": "c",
            "user_id": 1,
            "scope": ToolScope.MAINTAINER,
            "sphere_id": None,
            "event_id": None,
        }
        store.put("code-1", data, ttl_seconds=60)

        assert store.take("code-1") == data
        assert store.take("code-1") is None
        assert store.take("never-issued") is None
