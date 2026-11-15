"""Ways to get revocations and member lists to the chat Worker after commit.

`SCHEDULER_MODE` picks between them the way it does for the other
schedulers: DBOS retries delivery durably, the inline outbox tries once and
leaves the pass to expire on its own if the Worker is away.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction

from ludamus.links.db.django.parley_conversations import ParleyConversationRepository
from ludamus.links.db.django.staff_thread import thread_post_claims
from ludamus.links.encryption import JwtSigner
from ludamus.links.parley_worker import ParleyWorkerClient
from ludamus.mills.parley import sign_revocations
from ludamus.mills.parley_conversations import sign_membership
from ludamus.pacts.parley import (
    ParleyMessageReaderProtocol,
    ParleyReportedMessage,
    ParleyWorkerUnavailableError,
)

if TYPE_CHECKING:
    from ludamus.pacts.staff_cases import StaffThreadEntry

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


def deliver_membership(conversation_id: int) -> None:
    # Signed at delivery, so every attempt carries who is in it now.
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    ParleyWorkerClient(agent_host).sync_conversation(
        sign_membership(
            signer=JwtSigner(private_key),
            repository=ParleyConversationRepository(),
            conversation_id=conversation_id,
            now=datetime.now(UTC),
        )
    )


class InlineParleyMembershipOutbox:
    @staticmethod
    def schedule(*, conversation_ids: list[int]) -> None:
        def deliver() -> None:
            for conversation_id in conversation_ids:
                try:
                    deliver_membership(conversation_id)
                except Exception:
                    # The Worker keeps its last member list until the next
                    # change reaches it; the change itself must not fail.
                    logger.exception(
                        "parley membership sync failed: conversation=%s",
                        conversation_id,
                    )

        if conversation_ids:
            transaction.on_commit(deliver)


class DisabledParleyMembershipOutbox:
    @staticmethod
    def schedule(*, conversation_ids: list[int]) -> None:
        logger.debug(
            "parley not configured, membership sync dropped: conversations=%s",
            conversation_ids,
        )


class UnconfiguredParleyMessages:
    """No Worker to ask: a report is kept without its message."""

    @staticmethod
    def read_message(_token: str, /) -> ParleyReportedMessage | None:
        raise ParleyWorkerUnavailableError

    @staticmethod
    def moderate(_token: str, /) -> None:
        raise ParleyWorkerUnavailableError


def parley_message_reader() -> ParleyMessageReaderProtocol:
    agent_host: str = settings.PARLEY_AGENT_HOST
    return (
        ParleyWorkerClient(agent_host) if agent_host else UnconfiguredParleyMessages()
    )


def deliver_thread_post(entry: StaffThreadEntry) -> None:
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    ParleyWorkerClient(agent_host).post_to_conversation(
        JwtSigner(private_key).sign(thread_post_claims(entry, now=datetime.now(UTC)))
    )


class InlineStaffThread:
    """Posts into a case's thread after commit, once; the case stands without it."""

    @staticmethod
    def post(entry: StaffThreadEntry) -> None:
        def deliver() -> None:
            try:
                deliver_thread_post(entry)
            except Exception:
                logger.exception(
                    "staff thread post failed: thread=%s event=%s",
                    entry.thread_id,
                    entry.message.event,
                )

        transaction.on_commit(deliver)


class DisabledStaffThread:
    @staticmethod
    def post(entry: StaffThreadEntry) -> None:
        logger.debug(
            "parley not configured, staff thread post dropped: thread=%s",
            entry.thread_id,
        )
