"""The Worker's signed word on someone's unread mentions: an HS256 JWT."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ludamus.pacts.parley_mentions import (
    PARLEY_MENTIONS_AUDIENCE,
    PARLEY_MENTIONS_ISSUER,
    ParleyMentionClaims,
    ParleyMentionClaimsError,
    ParleyMentionsOffError,
    ParleyMentionTokenError,
    ParleyMentionVerifierProtocol,
)

if TYPE_CHECKING:
    from datetime import datetime

_LEEWAY_SECONDS = 30


class _Header(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alg: Literal["HS256"]
    typ: Literal["JWT"]


def _decoded(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


class HmacMentionVerifier(ParleyMentionVerifierProtocol):
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def verify(self, token: str, *, now: datetime) -> ParleyMentionClaims:
        if not self._secret:
            raise ParleyMentionsOffError
        payload = self._signed_payload(token)
        try:
            claims = ParleyMentionClaims.model_validate_json(payload)
        except ValidationError as error:
            raise ParleyMentionClaimsError from error
        if (
            claims.iss != PARLEY_MENTIONS_ISSUER
            or claims.aud != PARLEY_MENTIONS_AUDIENCE
            or claims.exp + _LEEWAY_SECONDS < now.timestamp()
        ):
            raise ParleyMentionTokenError
        return claims

    def _signed_payload(self, token: str) -> bytes:
        try:
            header, payload, signature = token.split(".")
            signed = _decoded(signature)
        except ValueError as error:
            raise ParleyMentionTokenError from error
        expected = hmac.new(
            self._secret, f"{header}.{payload}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, signed):
            raise ParleyMentionTokenError
        try:
            _Header.model_validate_json(_decoded(header), strict=True)
            return _decoded(payload)
        except ValueError as error:
            raise ParleyMentionTokenError from error
