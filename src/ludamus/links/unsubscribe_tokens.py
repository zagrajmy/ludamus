"""Signed one-click unsubscribe tokens for sphere announcement emails.

Django-signed payloads, no DB table, same pattern as the email-verification
tokens. They never expire: an unsubscribe link has to keep working for as
long as the mail it came in sits in someone's inbox.
"""

from __future__ import annotations

from django.core import signing
from pydantic import ValidationError

from ludamus.pacts.dashboard import (
    SphereUnsubscribeTokenCodecProtocol,
    SphereUnsubscribeTokenPayload,
)

SIGNING_SALT = "ludamus.sphere-unsubscribe"


class DjangoSphereUnsubscribeTokenCodec(SphereUnsubscribeTokenCodecProtocol):
    @staticmethod
    def dumps(payload: SphereUnsubscribeTokenPayload) -> str:
        data: dict[str, str | int] = payload.model_dump(mode="json")
        return signing.dumps(data, salt=SIGNING_SALT)

    @staticmethod
    def loads(token: str) -> SphereUnsubscribeTokenPayload | None:
        try:
            raw: dict[str, str | int] = signing.loads(token, salt=SIGNING_SALT)
        except signing.BadSignature:
            return None
        try:
            return SphereUnsubscribeTokenPayload.model_validate(raw)
        except ValidationError:
            return None
