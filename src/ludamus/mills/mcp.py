"""OAuth for MCP clients identified by Client ID Metadata Documents (CIMD).

A client's `client_id` is an HTTPS URL; the JSON document behind it lists the
redirect URIs the client may use. There is no registration step, so any MCP
client can connect, and the user decides at the consent screen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from ludamus.pacts.mcp import (
    McpClientDTO,
    McpClientRejectedError,
    McpGrantDTO,
    McpGrantRejectedError,
)

if TYPE_CHECKING:
    from ludamus.pacts.mcp import (
        AuthorizationCodeStoreProtocol,
        ClientMetadataDocument,
        ClientMetadataFetcherProtocol,
        McpAuthorizationData,
    )

AUTHORIZATION_CODE_TTL_SECONDS = 60
CLIENT_NAME_MAX_LENGTH = 100
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# RFC 7636 §4.1: 43-128 characters from the unreserved set.
CODE_VERIFIER_PATTERN = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
# Schemes a browser would run or read locally instead of handing to a client.
FORBIDDEN_REDIRECT_SCHEMES = frozenset({"javascript", "data", "file", "vbscript"})


class McpAuthorizationService:
    def __init__(
        self,
        *,
        fetcher: ClientMetadataFetcherProtocol,
        codes: AuthorizationCodeStoreProtocol,
    ) -> None:
        self._fetcher = fetcher
        self._codes = codes

    def resolve_client(self, *, client_id: str, redirect_uri: str) -> McpClientDTO:
        _check_client_id(client_id)
        document = self._fetcher.fetch(client_id)
        if document.get("client_id") != client_id:
            msg = "The client metadata document names a different client_id."
            raise McpClientRejectedError(msg)
        if document.get("token_endpoint_auth_method", "none") != "none":
            msg = "Only public clients (token_endpoint_auth_method none) can connect."
            raise McpClientRejectedError(msg)
        if not (registered := document.get("redirect_uris")):
            msg = "The client metadata document has no redirect_uris."
            raise McpClientRejectedError(msg)
        _check_redirect_uri(redirect_uri)
        if not any(_redirect_matches(uri, redirect_uri) for uri in registered):
            msg = "The redirect_uri is not listed in the client metadata document."
            raise McpClientRejectedError(msg)
        host = urlsplit(client_id).hostname or client_id
        return McpClientDTO(
            client_id=client_id,
            client_name=_client_name(document, fallback=host),
            client_host=host,
            redirect_uri=redirect_uri,
        )

    def issue_code(self, data: McpAuthorizationData) -> str:
        code = secrets.token_urlsafe(32)
        self._codes.put(code, data, ttl_seconds=AUTHORIZATION_CODE_TTL_SECONDS)
        return code

    def redeem_code(
        self, *, code: str, client_id: str, redirect_uri: str, code_verifier: str
    ) -> McpGrantDTO:
        if (data := self._codes.take(code)) is None:
            msg = "The authorization code is invalid, expired, or already used."
            raise McpGrantRejectedError(msg)
        if data["client_id"] != client_id or data["redirect_uri"] != redirect_uri:
            msg = "The authorization code was issued to a different client."
            raise McpGrantRejectedError(msg)
        if not _pkce_matches(verifier=code_verifier, challenge=data["code_challenge"]):
            msg = "The code_verifier does not match the code_challenge."
            raise McpGrantRejectedError(msg)
        return McpGrantDTO(
            client_id=client_id,
            user_id=data["user_id"],
            scope=data["scope"],
            sphere_id=data["sphere_id"],
            event_id=data["event_id"],
        )


def _check_client_id(client_id: str) -> None:
    parts = urlsplit(client_id)
    problems = (
        parts.scheme != "https",
        not parts.hostname,
        parts.username is not None or parts.password is not None,
        bool(parts.fragment),
        parts.path in {"", "/"},
        bool({".", ".."} & set(parts.path.split("/"))),
    )
    if any(problems):
        msg = "The client_id must be an https URL of a client metadata document."
        raise McpClientRejectedError(msg)


def _check_redirect_uri(redirect_uri: str) -> None:
    parts = urlsplit(redirect_uri)
    if not parts.scheme or parts.scheme in FORBIDDEN_REDIRECT_SCHEMES:
        msg = "The redirect_uri scheme cannot receive an authorization code."
        raise McpClientRejectedError(msg)
    if parts.fragment:
        msg = "The redirect_uri must not contain a fragment."
        raise McpClientRejectedError(msg)
    # OAuth 2.1 §7.5.1: plain http only on the user's own machine.
    if parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS:
        msg = "An http redirect_uri must point at localhost."
        raise McpClientRejectedError(msg)


def _redirect_matches(registered: str, requested: str) -> bool:
    if registered == requested:
        return True
    # RFC 8252 §7.3: native apps listen on an ephemeral loopback port, so the
    # port is the one part of a loopback redirect that may differ.
    reg, req = urlsplit(registered), urlsplit(requested)
    return (
        reg.scheme == req.scheme == "http"
        and reg.hostname in LOOPBACK_HOSTS
        and reg.hostname == req.hostname
        and reg.path == req.path
        and reg.query == req.query
    )


def _client_name(document: ClientMetadataDocument, *, fallback: str) -> str:
    if name := document.get("client_name", "").strip():
        return name[:CLIENT_NAME_MAX_LENGTH]
    return fallback


def _pkce_matches(*, verifier: str, challenge: str) -> bool:
    if not CODE_VERIFIER_PATTERN.fullmatch(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)
