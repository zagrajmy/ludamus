"""Signed links that let an order's email hand the order to an account.

Django-signed payloads, no table, like the email-verification tokens. The
payload binds the order and the account; expiry is `ORDER_CLAIM_LINK_MAX_AGE`,
enforced on read, and single use falls out of the claim itself.
"""

from __future__ import annotations

from django.core import signing
from pydantic import ValidationError

from ludamus.pacts.tickets import (
    ORDER_CLAIM_LINK_MAX_AGE,
    OrderClaimCodecProtocol,
    OrderClaimPayload,
)

SIGNING_SALT = "ludamus.ticket-order-claim"


class DjangoOrderClaimCodec(OrderClaimCodecProtocol):
    @staticmethod
    def dumps(payload: OrderClaimPayload) -> str:
        data: dict[str, int] = payload.model_dump()
        return signing.dumps(data, salt=SIGNING_SALT)

    @staticmethod
    def loads(token: str) -> OrderClaimPayload | None:
        try:
            raw: dict[str, int] = signing.loads(
                token, salt=SIGNING_SALT, max_age=ORDER_CLAIM_LINK_MAX_AGE
            )
        except signing.BadSignature:
            return None
        try:
            return OrderClaimPayload.model_validate(raw)
        except ValidationError:
            return None
