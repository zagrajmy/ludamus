"""MCP gate contracts: caller identity, tool tiers, and OAuth client access."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypedDict


class ToolScope(StrEnum):
    MAINTAINER = "maintainer"
    ORGANIZER = "organizer"


@dataclass(frozen=True, slots=True)
class ActorContext:
    user_id: int
    scope: ToolScope
    sphere_id: int | None = None
    event_id: int | None = None


@dataclass(frozen=True, slots=True)
class McpClientDTO:
    """An MCP client vouched for by its Client ID Metadata Document."""

    client_id: str
    client_name: str
    # Shown beside the self-declared name, which anyone can set to "Claude".
    client_host: str
    redirect_uri: str


class ClientMetadataDocument(TypedDict, total=False):
    """The fields of a Client ID Metadata Document this server reads."""

    client_id: str
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str


class McpAuthorizationData(TypedDict):
    """What the user approved, bound to the client that asked for it."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    user_id: int
    scope: ToolScope
    sphere_id: int | None
    event_id: int | None


@dataclass(frozen=True, slots=True)
class McpGrantDTO:
    client_id: str
    user_id: int
    scope: ToolScope
    sphere_id: int | None
    event_id: int | None


class McpClientRejectedError(Exception):
    """The client_id, its metadata document, or the redirect_uri is unusable.

    The message is safe to show the user: it never echoes the fetched body.
    """


class McpGrantRejectedError(Exception):
    """The authorization code is unknown, spent, expired, or not this client's."""


class ClientMetadataFetcherProtocol(Protocol):
    def fetch(self, url: str) -> ClientMetadataDocument:
        """Return the metadata document at `url`; raise `McpClientRejectedError`."""


class AuthorizationCodeStoreProtocol(Protocol):
    @staticmethod
    def put(code: str, data: McpAuthorizationData, *, ttl_seconds: int) -> None: ...
    @staticmethod
    def take(code: str) -> McpAuthorizationData | None:
        """Return the grant once; later calls with the same code get None."""


class McpAuthorizationServiceProtocol(Protocol):
    def resolve_client(self, *, client_id: str, redirect_uri: str) -> McpClientDTO: ...
    def issue_code(self, data: McpAuthorizationData) -> str: ...
    def redeem_code(
        self, *, code: str, client_id: str, redirect_uri: str, code_verifier: str
    ) -> McpGrantDTO: ...
