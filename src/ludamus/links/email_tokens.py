"""Signed email-verification tokens.

Django-signed payloads, no DB table — same pattern as the MCP tokens. The
payload carries the action, the user and the address being proven; expiry is
`EMAIL_LINK_MAX_AGE` enforced on read, single-use falls out of the state
check redemption runs anyway.
"""

from __future__ import annotations

from typing import cast

from django.core import signing
from pydantic import ValidationError

from ludamus.pacts.crowd import (
    EMAIL_LINK_MAX_AGE,
    EmailTokenCodecProtocol,
    EmailTokenPayload,
)

SIGNING_SALT = "ludamus.email-verification"


class DjangoEmailTokenCodec(EmailTokenCodecProtocol):
    @staticmethod
    def dumps(payload: EmailTokenPayload) -> str:
        data: dict[str, str | int] = {
            "act": payload.act.value,
            "uid": payload.uid,
            "addr": payload.addr,
        }
        return signing.dumps(data, salt=SIGNING_SALT)

    @staticmethod
    def loads(token: str) -> EmailTokenPayload | None:
        try:
            # signing.loads is typed Any; the payload is parsed right here at
            # the boundary, so the untyped value never travels further.
            raw = cast(
                "object",
                signing.loads(token, salt=SIGNING_SALT, max_age=EMAIL_LINK_MAX_AGE),
            )
        except signing.BadSignature:
            return None
        try:
            return EmailTokenPayload.model_validate(raw)
        except ValidationError:
            return None
