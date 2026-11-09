"""Ways to get a revocation to the chat Worker once its transaction commits.

`SCHEDULER_MODE` picks between them the way it does for the other
schedulers: DBOS retries delivery durably, the inline outbox tries once and
leaves the pass to expire on its own if the Worker is away.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction

from ludamus.links.encryption import JwtSigner
from ludamus.links.parley_worker import ParleyWorkerClient
from ludamus.mills.parley import sign_revocations

logger = logging.getLogger(__name__)


def deliver_revocations(*, sphere_ids: list[int], subject: str) -> None:
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    client = ParleyWorkerClient(agent_host)
    for token in sign_revocations(
        signer=JwtSigner(private_key),
        sphere_ids=sphere_ids,
        subject=subject,
        now=datetime.now(UTC),
    ):
        client.revoke(token)


class InlineParleyRevocationOutbox:
    @staticmethod
    def schedule(*, sphere_ids: list[int], subject: str) -> None:
        def deliver() -> None:
            try:
                deliver_revocations(sphere_ids=sphere_ids, subject=subject)
            except Exception:
                # A revocation the Worker never hears of still ends when the
                # pass expires; the change that caused it must not fail.
                logger.exception(
                    "parley revocation failed: spheres=%s subject=%s",
                    sphere_ids,
                    subject,
                )

        transaction.on_commit(deliver)


class DisabledParleyRevocationOutbox:
    @staticmethod
    def schedule(*, sphere_ids: list[int], subject: str) -> None:
        logger.debug(
            "parley not configured, revocation dropped: spheres=%s subject=%s",
            sphere_ids,
            subject,
        )
