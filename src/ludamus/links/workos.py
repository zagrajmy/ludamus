"""WorkOS AuthKit as the identity provider behind login and logout."""

from __future__ import annotations

import base64
import binascii
import logging
from functools import cached_property
from typing import TYPE_CHECKING, TypedDict

from pydantic import TypeAdapter, ValidationError
from workos import WorkOSClient, WorkOSError

from ludamus.pacts.crowd import (
    IdentityDTO,
    IdentityProviderProtocol,
    IdentityRejectedError,
)

if TYPE_CHECKING:
    from workos.common.models.user import User

logger = logging.getLogger(__name__)


class _AccessTokenClaims(TypedDict):
    sid: str


_CLAIMS = TypeAdapter(_AccessTokenClaims)


class WorkOSIdentityProvider(IdentityProviderProtocol):
    def __init__(self, *, api_key: str, client_id: str) -> None:
        self._api_key = api_key
        self._client_id = client_id

    @cached_property
    def _client(self) -> WorkOSClient:
        return WorkOSClient(api_key=self._api_key, client_id=self._client_id)

    def authorization_url(self, *, redirect_uri: str, state: str, sign_up: bool) -> str:
        return self._client.user_management.get_authorization_url(
            provider="authkit",
            redirect_uri=redirect_uri,
            state=state,
            screen_hint="sign-up" if sign_up else None,
        )

    def authenticate(self, code: str) -> IdentityDTO:
        try:
            response = self._client.user_management.authenticate_with_code(code=code)
            session_id = _session_id(response.access_token)
        except (WorkOSError, IdentityRejectedError) as exc:
            logger.warning("WorkOS rejected the authorization code: %s", exc)
            msg = "The identity provider rejected the login."
            raise IdentityRejectedError(msg) from exc
        user = response.user
        return IdentityDTO(
            provider_user_id=user.id,
            email=user.email,
            email_verified=user.email_verified,
            name=_display_name(user),
            avatar_url=user.profile_picture_url or "",
            legacy_id=user.external_id or "",
            session_id=session_id,
        )

    def logout_url(self, *, session_id: str, return_to: str) -> str:
        return self._client.user_management.get_logout_url(
            session_id=session_id, return_to=return_to
        )


def _display_name(user: User) -> str:
    if user.name and user.name.strip():
        return user.name.strip()
    parts = (part.strip() for part in (user.first_name, user.last_name) if part)
    return " ".join(part for part in parts if part)


def _session_id(access_token: str) -> str:
    # NOTE: the token came straight from WorkOS over TLS in the code exchange,
    # so reading the session id needs no signature check.
    try:
        payload = access_token.split(".")[1]
        claims = _CLAIMS.validate_json(base64.urlsafe_b64decode(payload + "=" * 4))
    except (IndexError, binascii.Error, ValidationError) as exc:
        msg = "The access token carries no session id."
        raise IdentityRejectedError(msg) from exc
    return claims["sid"]
