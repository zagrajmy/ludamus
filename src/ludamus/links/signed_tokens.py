"""Django-signed payload tokens: no DB table, the signature is the record.

Email-verification links expire after `EMAIL_LINK_MAX_AGE`, enforced on read;
single use falls out of the state check redemption runs anyway. Unsubscribe
links never expire: one has to keep working for as long as the mail it came
in sits in someone's inbox. Each kind signs with its own salt, so a token
minted for one can never be read as the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core import signing
from pydantic import BaseModel, ValidationError

from ludamus.pacts.dashboard import (
    SphereUnsubscribeTokenCodecProtocol,
    SphereUnsubscribeTokenPayload,
)
from ludamus.pacts.parley_mentions import (
    ParleyMentionUnsubscribeCodecProtocol,
    ParleyMentionUnsubscribePayload,
)
from ludamus.pacts.user import (
    EMAIL_LINK_MAX_AGE,
    EmailTokenCodecProtocol,
    EmailTokenPayload,
)

if TYPE_CHECKING:
    from datetime import timedelta

EMAIL_VERIFICATION_SALT = "ludamus.email-verification"
SPHERE_UNSUBSCRIBE_SALT = "ludamus.sphere-unsubscribe"
PARLEY_MENTION_UNSUBSCRIBE_SALT = "ludamus.parley-mention-unsubscribe"


class _SignedPayloadCodec[PayloadT: BaseModel]:
    def __init__(
        self,
        *,
        payload_type: type[PayloadT],
        salt: str,
        max_age: timedelta | None = None,
        by_alias: bool = False,
    ) -> None:
        self._payload_type = payload_type
        self._salt = salt
        self._max_age = max_age
        self._by_alias = by_alias

    def dumps(self, payload: PayloadT) -> str:
        data: dict[str, str | int] = payload.model_dump(
            mode="json", by_alias=self._by_alias
        )
        return signing.dumps(data, salt=self._salt)

    def loads(self, token: str) -> PayloadT | None:
        try:
            # signing.loads is typed Any; annotating the shape `dumps` wrote
            # stops it there instead of letting it travel further untyped.
            raw: dict[str, str | int] = signing.loads(
                token, salt=self._salt, max_age=self._max_age
            )
        except signing.BadSignature:
            return None
        try:
            return self._payload_type.model_validate(raw)
        except ValidationError:
            return None


class DjangoEmailTokenCodec(
    _SignedPayloadCodec[EmailTokenPayload], EmailTokenCodecProtocol
):
    def __init__(self) -> None:
        # The payload's aliases are the wire keys and keep the link short.
        super().__init__(
            payload_type=EmailTokenPayload,
            salt=EMAIL_VERIFICATION_SALT,
            max_age=EMAIL_LINK_MAX_AGE,
            by_alias=True,
        )


class DjangoSphereUnsubscribeTokenCodec(
    _SignedPayloadCodec[SphereUnsubscribeTokenPayload],
    SphereUnsubscribeTokenCodecProtocol,
):
    def __init__(self) -> None:
        super().__init__(
            payload_type=SphereUnsubscribeTokenPayload, salt=SPHERE_UNSUBSCRIBE_SALT
        )


class DjangoParleyMentionUnsubscribeCodec(
    _SignedPayloadCodec[ParleyMentionUnsubscribePayload],
    ParleyMentionUnsubscribeCodecProtocol,
):
    def __init__(self) -> None:
        super().__init__(
            payload_type=ParleyMentionUnsubscribePayload,
            salt=PARLEY_MENTION_UNSUBSCRIBE_SALT,
        )
