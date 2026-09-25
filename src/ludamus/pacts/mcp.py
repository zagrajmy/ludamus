"""MCP gate contracts: caller identity, tool tiers, and OAuth client access."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict


class ToolScope(StrEnum):
    MAINTAINER = "maintainer"
    ORGANIZER = "organizer"


@dataclass(frozen=True, slots=True)
class ActorContext:
    user_id: int
    scope: ToolScope
    sphere_id: int | None = None
    event_id: int | None = None


class ClientRejection(StrEnum):
    """Why an MCP client can't start an authorization; shown to the user."""

    BAD_CLIENT_ID = "bad_client_id"
    UNREACHABLE = "unreachable"
    NOT_PUBLIC = "not_public"
    INVALID_DOCUMENT = "invalid_document"
    CLIENT_ID_MISMATCH = "client_id_mismatch"
    CONFIDENTIAL_CLIENT = "confidential_client"
    NO_REDIRECT_URIS = "no_redirect_uris"
    BAD_REDIRECT_URI = "bad_redirect_uri"
    REDIRECT_NOT_LISTED = "redirect_not_listed"


class McpClientRejectedError(Exception):
    """The client can't be trusted with a redirect, so the user reads why."""

    def __init__(self, reason: ClientRejection) -> None:
        super().__init__(reason.value)
        self.reason = reason


class ClientMetadataDocument(TypedDict, total=False):
    """The fields of a Client ID Metadata Document this server reads."""

    client_id: str
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str


class McpClientDTO(BaseModel):
    """An MCP client vouched for by its Client ID Metadata Document."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    client_name: str
    # Shown beside the self-declared name, which anyone can set to "Claude".
    client_host: str
    redirect_uri: str


class McpAuthorizationRequest(TypedDict):
    """An /authorize request, parsed; `scope` is None for a foreign resource."""

    client_id: str
    redirect_uri: str
    response_type: str
    code_challenge: str
    code_challenge_method: str
    state: str | None
    scope: ToolScope | None


class McpPendingAuthorizationDTO(BaseModel):
    """A vetted request waiting on the user's decision."""

    model_config = ConfigDict(frozen=True)

    client: McpClientDTO
    scope: ToolScope
    code_challenge: str
    state: str | None


class McpAuthorizationRejectedError(Exception):
    """An OAuth error to send back to the client's verified redirect_uri."""

    def __init__(
        self, *, error: str, description: str, redirect_uri: str, state: str | None
    ) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.redirect_uri = redirect_uri
        self.state = state


class McpEventChoiceDTO(BaseModel):
    pk: int
    name: str


class McpConsentDTO(BaseModel):
    may_grant: bool
    # Organizer consent only; the default choice comes first.
    events: list[McpEventChoiceDTO]


@dataclass(frozen=True, slots=True)
class MaintainerGrant:
    user_id: int


@dataclass(frozen=True, slots=True)
class OrganizerGrant:
    user_id: int
    sphere_id: int
    event_id: int


type McpGrant = MaintainerGrant | OrganizerGrant


@dataclass(frozen=True, slots=True)
class McpIssuedCode:
    """What an authorization code stands for, bound to the client it went to."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    grant: McpGrant


class McpGrantRejectedError(Exception):
    """The authorization code is unknown, spent, expired, or not this client's."""


class ClientMetadataFetcherProtocol(Protocol):
    @staticmethod
    def fetch(url: str) -> ClientMetadataDocument:
        """Return the metadata document at `url`; raise `McpClientRejectedError`."""


class AuthorizationCodeStoreProtocol(Protocol):
    @staticmethod
    def put(code: str, issued: McpIssuedCode, *, ttl_seconds: int) -> None: ...
    @staticmethod
    def take(code: str) -> McpIssuedCode | None:
        """Return the grant once; later calls with the same code get None."""


class McpAuthorizationServiceProtocol(Protocol):
    def begin(self, request: McpAuthorizationRequest) -> McpPendingAuthorizationDTO: ...
    def consent(
        self, pending: McpPendingAuthorizationDTO, *, sphere_id: int, user_slug: str
    ) -> McpConsentDTO: ...
    def approve(
        self,
        pending: McpPendingAuthorizationDTO,
        *,
        user_id: int,
        user_slug: str,
        sphere_id: int,
        event_id: int | None,
    ) -> str: ...
    def redeem(
        self, *, code: str, client_id: str, redirect_uri: str, code_verifier: str
    ) -> McpGrant: ...
