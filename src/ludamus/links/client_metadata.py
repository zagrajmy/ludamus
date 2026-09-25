"""Fetches OAuth Client ID Metadata Documents on behalf of the MCP consent flow.

The URL comes from whoever starts an authorization, so this is a server-side
request to an address a stranger chose: only public addresses, no redirects,
a short timeout, and a small body cap.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

import requests
from pydantic import TypeAdapter, ValidationError

from ludamus.pacts.mcp import (
    ClientMetadataDocument,
    ClientMetadataFetcherProtocol,
    McpClientRejectedError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# The CIMD draft suggests authorization servers cap documents at 5 KB.
MAX_DOCUMENT_BYTES = 5 * 1024
TIMEOUT_SECONDS = 5
HTTPS_PORT = 443
HTTP_OK = 200
_DOCUMENT = TypeAdapter(ClientMetadataDocument)


class HttpClientMetadataFetcher(ClientMetadataFetcherProtocol):
    def fetch(self, url: str) -> ClientMetadataDocument:
        parts = urlsplit(url)
        self._require_public_host(parts.hostname or "", parts.port or HTTPS_PORT)
        # SAFETY: requests resolves the name again, so a DNS answer that flips
        # between the check and the connect (rebinding) still slips through.
        # The response is never shown back, which keeps that blind.
        try:
            response = requests.get(
                url,
                timeout=TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
                headers={"Accept": "application/json"},
            )
        except requests.RequestException as exc:
            logger.info("CIMD fetch failed for %s: %s", url, exc)
            msg = "The client metadata document could not be fetched."
            raise McpClientRejectedError(msg) from exc
        with response:
            if response.status_code != HTTP_OK:
                logger.info("CIMD fetch got %s for %s", response.status_code, url)
                msg = (
                    "The client metadata document answered with HTTP "
                    f"{response.status_code}."
                )
                raise McpClientRejectedError(msg)
            body = _read_capped(response)
        try:
            return _DOCUMENT.validate_json(body)
        except ValidationError as exc:
            msg = "The client metadata document is not valid client metadata."
            raise McpClientRejectedError(msg) from exc

    @staticmethod
    def _require_public_host(host: str, port: int) -> None:
        try:
            infos = socket.getaddrinfo(host, port)
        except OSError as exc:
            msg = "The client metadata host does not resolve."
            raise McpClientRejectedError(msg) from exc
        addresses = {
            ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos
        }
        if not addresses or not all(address.is_global for address in addresses):
            logger.warning("CIMD fetch refused for non-public host %s", host)
            msg = "The client metadata host is not a public address."
            raise McpClientRejectedError(msg)


class _ChunkReader(Protocol):
    def __call__(self, chunk_size: int) -> Iterator[bytes]: ...


def _read_capped(response: requests.Response) -> bytes:
    # requests' stubs return untyped chunks; binding names what they are.
    read_chunks: _ChunkReader = response.iter_content
    body = b""
    for chunk in read_chunks(1024):
        body += chunk
        if len(body) > MAX_DOCUMENT_BYTES:
            msg = "The client metadata document is larger than 5 KB."
            raise McpClientRejectedError(msg)
    return body
