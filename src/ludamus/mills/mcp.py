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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NoReturn
from urllib.parse import urlsplit

from ludamus.pacts import NotFoundError
from ludamus.pacts.mcp import (
    ClientRejection,
    MaintainerGrant,
    McpAuthorizationRejectedError,
    McpClientDTO,
    McpClientRejectedError,
    McpConsentDTO,
    McpEventChoiceDTO,
    McpGrantRejectedError,
    McpIssuedCode,
    McpPendingAuthorizationDTO,
    OrganizerGrant,
    ToolScope,
)

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.legacy import EventDTO
    from ludamus.pacts.mcp import (
        AuthorizationCodeStoreProtocol,
        ClientMetadataDocument,
        ClientMetadataFetcherProtocol,
        McpAuthorizationRequest,
        McpGrant,
    )
    from ludamus.pacts.multiverse import SpherePanelServiceProtocol

AUTHORIZATION_CODE_TTL_SECONDS = 60
CLIENT_NAME_MAX_LENGTH = 100
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# RFC 7636 §4.1: 43-128 characters from the unreserved set.
CODE_VERIFIER_PATTERN = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
# Schemes a browser would run or read locally instead of handing to a client.
FORBIDDEN_REDIRECT_SCHEMES = frozenset({"javascript", "data", "file", "vbscript"})
INVALID_GRANT = "The authorization code is invalid or was issued for another request."


class McpAuthorizationService:
    def __init__(
        self,
        *,
        fetcher: ClientMetadataFetcherProtocol,
        codes: AuthorizationCodeStoreProtocol,
        spheres: SpherePanelServiceProtocol,
        users: UserRepositoryProtocol,
    ) -> None:
        self._fetcher = fetcher
        self._codes = codes
        self._spheres = spheres
        self._users = users

    def begin(self, request: McpAuthorizationRequest) -> McpPendingAuthorizationDTO:
        client = self._resolve_client(
            client_id=request["client_id"], redirect_uri=request["redirect_uri"]
        )
        pending = McpPendingAuthorizationDTO(
            client=client,
            scope=request["scope"] or ToolScope.MAINTAINER,
            code_challenge=request["code_challenge"],
            state=request["state"],
        )
        if request["response_type"] != "code":
            _reject(pending, "unsupported_response_type", "Only code is supported.")
        if request["code_challenge_method"] != "S256" or not pending.code_challenge:
            _reject(pending, "invalid_request", "PKCE with S256 is required.")
        if request["scope"] is None:
            _reject(pending, "invalid_target", "The resource must be /mcp/ here.")
        return pending

    def consent(
        self, pending: McpPendingAuthorizationDTO, *, sphere_id: int, user_slug: str
    ) -> McpConsentDTO:
        if not self._may_grant(pending.scope, sphere_id=sphere_id, user_slug=user_slug):
            return McpConsentDTO(may_grant=False, events=[])
        if pending.scope is ToolScope.MAINTAINER:
            return McpConsentDTO(may_grant=True, events=[])
        events = sorted(self._spheres.list_events(sphere_id), key=_soonest_first)
        return McpConsentDTO(
            may_grant=True,
            events=[
                McpEventChoiceDTO(pk=event.pk, name=event.name) for event in events
            ],
        )

    def approve(
        self,
        pending: McpPendingAuthorizationDTO,
        *,
        user_id: int,
        user_slug: str,
        sphere_id: int,
        event_id: int | None,
    ) -> str:
        if not self._may_grant(pending.scope, sphere_id=sphere_id, user_slug=user_slug):
            _reject(pending, "access_denied", "The user may not grant this access.")
        grant: McpGrant = MaintainerGrant(user_id=user_id)
        if pending.scope is ToolScope.ORGANIZER:
            sphere_events = {event.pk for event in self._spheres.list_events(sphere_id)}
            if event_id is None or event_id not in sphere_events:
                raise NotFoundError
            grant = OrganizerGrant(
                user_id=user_id, sphere_id=sphere_id, event_id=event_id
            )
        code = secrets.token_urlsafe(32)
        self._codes.put(
            code,
            McpIssuedCode(
                client_id=pending.client.client_id,
                redirect_uri=pending.client.redirect_uri,
                code_challenge=pending.code_challenge,
                grant=grant,
            ),
            ttl_seconds=AUTHORIZATION_CODE_TTL_SECONDS,
        )
        return code

    def redeem(
        self, *, code: str, client_id: str, redirect_uri: str, code_verifier: str
    ) -> McpGrant:
        issued = self._codes.take(code)
        if (
            issued is None
            or issued.client_id != client_id
            or issued.redirect_uri != redirect_uri
            or not _pkce_matches(
                verifier=code_verifier, challenge=issued.code_challenge
            )
        ):
            raise McpGrantRejectedError(INVALID_GRANT)
        return issued.grant

    def _resolve_client(self, *, client_id: str, redirect_uri: str) -> McpClientDTO:
        _check_client_id(client_id)
        _check_redirect_uri(redirect_uri)
        document = self._fetcher.fetch(client_id)
        _check_document(document, client_id=client_id, redirect_uri=redirect_uri)
        host = urlsplit(client_id).hostname or client_id
        return McpClientDTO(
            client_id=client_id,
            client_name=_client_name(document, fallback=host),
            client_host=host,
            redirect_uri=redirect_uri,
        )

    def _may_grant(self, scope: ToolScope, *, sphere_id: int, user_slug: str) -> bool:
        if scope is ToolScope.ORGANIZER:
            return self._spheres.can_write_programme(sphere_id, user_slug)
        return self._users.read(user_slug).is_superuser


def _reject(
    pending: McpPendingAuthorizationDTO, error: str, description: str
) -> NoReturn:
    raise McpAuthorizationRejectedError(
        error=error, description=description, pending=pending
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
        raise McpClientRejectedError(ClientRejection.BAD_CLIENT_ID)


def _check_redirect_uri(redirect_uri: str) -> None:
    parts = urlsplit(redirect_uri)
    # OAuth 2.1 §7.5.1: plain http only on the user's own machine.
    if (
        not parts.scheme
        or parts.scheme in FORBIDDEN_REDIRECT_SCHEMES
        or parts.fragment
        or (parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS)
    ):
        raise McpClientRejectedError(ClientRejection.BAD_REDIRECT_URI)


def _check_document(
    document: ClientMetadataDocument, *, client_id: str, redirect_uri: str
) -> None:
    if document.get("client_id") != client_id:
        raise McpClientRejectedError(ClientRejection.CLIENT_ID_MISMATCH)
    if document.get("token_endpoint_auth_method", "none") != "none":
        raise McpClientRejectedError(ClientRejection.CONFIDENTIAL_CLIENT)
    if not (registered := document.get("redirect_uris")):
        raise McpClientRejectedError(ClientRejection.NO_REDIRECT_URIS)
    if not any(_redirect_matches(uri, redirect_uri) for uri in registered):
        raise McpClientRejectedError(ClientRejection.REDIRECT_NOT_LISTED)


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


def _soonest_first(event: EventDTO) -> tuple[bool, float]:
    # The first choice is the default: upcoming events soonest first, then
    # past ones newest first.
    ended = event.end_time < datetime.now(UTC)
    start = event.start_time.timestamp()
    return ended, -start if ended else start


def _pkce_matches(*, verifier: str, challenge: str) -> bool:
    if not CODE_VERIFIER_PATTERN.fullmatch(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)
