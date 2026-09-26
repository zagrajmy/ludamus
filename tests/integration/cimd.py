"""A stand-in for the network behind HttpClientMetadataFetcher.

It replaces urllib3's HTTPSConnectionPool and DNS, the lowest seams the
fetcher has, and records which address and TLS hostname each fetch used.
"""

import io
import json
import socket
from dataclasses import dataclass, field

import urllib3

PUBLIC_ADDRESS = "93.184.216.34"


@dataclass
class FetchRecord:
    address: str
    port: int
    path: str
    headers: dict
    server_hostname: str


@dataclass
class FakeMetadataServer:
    routes: dict = field(default_factory=dict)
    fetches: list = field(default_factory=list)

    def serve(self, path, *, document=None, status=200, body=None, error=None):
        if error is not None:
            self.routes[path] = error
            return
        raw = json.dumps(document).encode() if body is None else body
        self.routes[path] = (status, raw)

    def pool(self, address, port, **kwargs):
        return _Pool(server=self, address=address, port=port, kwargs=kwargs)


@dataclass
class _Pool:
    server: FakeMetadataServer
    address: str
    port: int
    kwargs: dict

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def urlopen(self, method, path, **kwargs):
        assert method == "GET"
        assert kwargs["redirect"] is False
        self.server.fetches.append(
            FetchRecord(
                address=self.address,
                port=self.port,
                path=path,
                headers=kwargs["headers"],
                server_hostname=self.kwargs["server_hostname"],
            )
        )
        route = self.server.routes[path]
        if isinstance(route, Exception):
            raise route
        status, body = route
        return urllib3.HTTPResponse(
            body=io.BytesIO(body), status=status, preload_content=False
        )


def resolves_to(*addresses):
    def resolve(_host, port, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]

    return resolve


def install(monkeypatch, *addresses):
    server = FakeMetadataServer()
    monkeypatch.setattr(
        "ludamus.links.client_metadata.HTTPSConnectionPool", server.pool
    )
    monkeypatch.setattr(
        socket, "getaddrinfo", resolves_to(*(addresses or [PUBLIC_ADDRESS]))
    )
    return server
