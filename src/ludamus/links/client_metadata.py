"""Fetches OAuth Client ID Metadata Documents on behalf of the MCP consent flow.

The URL comes from whoever starts an authorization, so this is a server-side
request to an address a stranger chose. The host is resolved once, every
address must be public, and the connection goes to the address that was
checked (TLS still verifies the real hostname), so a DNS answer that changes
between check and connect can't point it inward. No redirects, a deadline on
the whole exchange, and a 5 KB body cap.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError
from urllib3 import HTTPSConnectionPool, Timeout
from urllib3.exceptions import HTTPError

from ludamus.pacts.mcp import (
    ClientMetadataDocument,
    ClientMetadataFetcherProtocol,
    ClientRejection,
    McpClientRejectedError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# The CIMD draft suggests authorization servers cap documents at 5 KB.
MAX_DOCUMENT_BYTES = 5 * 1024
DEADLINE_SECONDS = 5
CHUNK_BYTES = 1024
HTTPS_PORT = 443
HTTP_OK = 200
_DOCUMENT = TypeAdapter(ClientMetadataDocument)


class HttpClientMetadataFetcher(ClientMetadataFetcherProtocol):
    @staticmethod
    def fetch(url: str) -> ClientMetadataDocument:
        deadline = time.monotonic() + DEADLINE_SECONDS
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port or HTTPS_PORT
        pool = HTTPSConnectionPool(
            _public_address(host, port),
            port,
            timeout=Timeout(total=DEADLINE_SECONDS),
            retries=False,
            assert_hostname=host,
            server_hostname=host,
        )
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        try:
            with pool:
                body = _get(pool, path=path, netloc=parts.netloc, deadline=deadline)
        except HTTPError as exc:
            logger.info("CIMD fetch failed for %s: %s", url, exc)
            raise McpClientRejectedError(ClientRejection.UNREACHABLE) from exc
        try:
            return _DOCUMENT.validate_json(body)
        except ValidationError as exc:
            raise McpClientRejectedError(ClientRejection.INVALID_DOCUMENT) from exc


def _get(
    pool: HTTPSConnectionPool, *, path: str, netloc: str, deadline: float
) -> bytes:
    response = pool.urlopen(
        "GET",
        path,
        headers={"Host": netloc, "Accept": "application/json"},
        redirect=False,
        preload_content=False,
    )
    try:
        if response.status != HTTP_OK:
            logger.info("CIMD fetch got %s for %s", response.status, netloc)
            raise McpClientRejectedError(ClientRejection.UNREACHABLE)
        return _read_capped(response.stream(CHUNK_BYTES), deadline)
    finally:
        response.release_conn()


def _public_address(host: str, port: int) -> str:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise McpClientRejectedError(ClientRejection.UNREACHABLE) from exc
    addresses = [
        ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos
    ]
    if not addresses or not all(address.is_global for address in addresses):
        logger.warning("CIMD fetch refused for non-public host %s", host)
        raise McpClientRejectedError(ClientRejection.NOT_PUBLIC)
    return str(addresses[0])


def _read_capped(chunks: Iterator[bytes], deadline: float) -> bytes:
    body = b""
    for chunk in chunks:
        body += chunk
        if len(body) > MAX_DOCUMENT_BYTES:
            raise McpClientRejectedError(ClientRejection.INVALID_DOCUMENT)
        # The socket timeout bounds each read; this bounds a slow trickle.
        if time.monotonic() > deadline:
            raise McpClientRejectedError(ClientRejection.UNREACHABLE)
    return body
