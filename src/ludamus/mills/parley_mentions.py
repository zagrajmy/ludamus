"""Mentions someone left unread, by email: whether, when and what.

The Worker knows what is unread; the app knows who may be mailed. A mention
from someone the reader blocked never reaches them, while one from someone
who blocked the reader still does: a block changes only the blocker's view.
"""

from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING

from ludamus.pacts.parley_mentions import (
    ParleyMentionChat,
    ParleyMentionDelivery,
    ParleyMentionDeliveryStatus,
    ParleyMentionDigest,
    ParleyMentionLine,
    ParleyMentionMailServiceProtocol,
    ParleyMentionUnsubscribePayload,
)
from ludamus.specs.parley import PARLEY_MENTION_MAIL_INTERVAL

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.parley import ParleyConversationRepositoryProtocol
    from ludamus.pacts.parley_mentions import (
        ParleyMention,
        ParleyMentionMailerProtocol,
        ParleyMentionRepositoryProtocol,
        ParleyMentionUnsubscribeCodecProtocol,
        ParleyMentionVerifierProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)

_CONVERSATION = re.compile(r"^conversation:(\d+)$")


def _mentioned_ids(body: str) -> set[int]:
    ids: set[int] = set()
    for chunk in body.split("<@")[1:]:
        head, closed, _rest = chunk.partition(">")
        if closed and head.isascii() and head.isdigit():
            ids.add(int(head))
    return ids


def _skipped(reason: str) -> ParleyMentionDelivery:
    return ParleyMentionDelivery(
        status=ParleyMentionDeliveryStatus.SKIPPED, reason=reason
    )


class ParleyMentionMailService(ParleyMentionMailServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        verifier: ParleyMentionVerifierProtocol,
        repository: ParleyMentionRepositoryProtocol,
        conversations: ParleyConversationRepositoryProtocol,
        mailer: ParleyMentionMailerProtocol,
        tokens: ParleyMentionUnsubscribeCodecProtocol,
    ) -> None:
        self._transaction = transaction
        self._verifier = verifier
        self._repository = repository
        self._conversations = conversations
        self._mailer = mailer
        self._tokens = tokens

    def deliver(self, *, token: str, now: datetime) -> ParleyMentionDelivery:
        claims = self._verifier.verify(token, now=now)
        user_id = int(claims.sub)
        delivery = self._deliver(user_id=user_id, mentions=claims.mentions, now=now)
        logger.info(
            "parley mention mail %s: user=%s mentions=%s reason=%s",
            delivery.status.value,
            user_id,
            len(claims.mentions),
            delivery.reason,
        )
        return delivery

    def _deliver(
        self, *, user_id: int, mentions: list[ParleyMention], now: datetime
    ) -> ParleyMentionDelivery:
        recipient = self._repository.read_recipient(user_id)
        if recipient is None or not recipient.active:
            return _skipped("inactive")
        if not recipient.enabled:
            return _skipped("off")
        if not recipient.mailable:
            return _skipped("no_address")
        kept = self._kept(user_id, mentions)
        names = self._names(kept)
        if not (chats := self._chats(user_id=user_id, mentions=kept, names=names)):
            return _skipped("nothing_left")
        if recipient.last_sent_at is not None:
            wait = recipient.last_sent_at + PARLEY_MENTION_MAIL_INTERVAL - now
            if wait.total_seconds() > 0:
                return ParleyMentionDelivery(
                    status=ParleyMentionDeliveryStatus.THROTTLED,
                    retry_after=math.ceil(wait.total_seconds()),
                )
        digest = ParleyMentionDigest(
            user_id=user_id,
            chats=chats,
            names=names,
            unsubscribe_token=self._tokens.dumps(
                ParleyMentionUnsubscribePayload(user_id=user_id)
            ),
        )
        if not self._mailer.send(digest):
            return _skipped("unsent")
        with self._transaction.atomic():
            self._repository.record_sent(user_id=user_id, at=now)
        return ParleyMentionDelivery(status=ParleyMentionDeliveryStatus.SENT)

    def _kept(self, user_id: int, mentions: list[ParleyMention]) -> list[ParleyMention]:
        blocked = {person.id for person in self._conversations.list_blocked(user_id)}
        return [
            mention
            for mention in mentions
            if mention.author != str(user_id) and mention.author not in blocked
        ]

    def _names(self, mentions: list[ParleyMention]) -> dict[str, str]:
        ids = {int(mention.author) for mention in mentions} | {
            found for mention in mentions for found in _mentioned_ids(mention.body)
        }
        return {str(pk): name for pk, name in self._repository.read_names(ids).items()}

    def _chats(
        self, *, user_id: int, mentions: list[ParleyMention], names: dict[str, str]
    ) -> list[ParleyMentionChat]:
        chats: dict[str, ParleyMentionChat] = {}
        titles: dict[str, str | None] = {}
        for mention in mentions:
            if mention.room not in titles:
                titles[mention.room] = self._title(user_id, mention.room)
            if (title := titles[mention.room]) is None:
                continue
            chat = chats.setdefault(
                mention.room,
                ParleyMentionChat(room_id=mention.room, title=title, lines=[]),
            )
            chat.lines.append(
                ParleyMentionLine(
                    author_name=names.get(mention.author, mention.author_name),
                    body=mention.body,
                )
            )
        return list(chats.values())

    def _title(self, user_id: int, room_id: str) -> str | None:
        if (match := _CONVERSATION.match(room_id)) is None:
            return None
        conversation = self._conversations.read_for(
            conversation_id=int(match[1]), user_id=user_id
        )
        return None if conversation is None else conversation.title

    def read_enabled(self, user_id: int) -> bool:
        return self._repository.read_enabled(user_id)

    def set_enabled(self, *, user_id: int, enabled: bool) -> None:
        with self._transaction.atomic():
            self._repository.set_enabled(user_id=user_id, enabled=enabled)

    def read_unsubscribe_token(
        self, token: str
    ) -> ParleyMentionUnsubscribePayload | None:
        return self._tokens.loads(token)

    def unsubscribe_by_token(
        self, token: str
    ) -> ParleyMentionUnsubscribePayload | None:
        if (payload := self._tokens.loads(token)) is None:
            return None
        self.set_enabled(user_id=payload.user_id, enabled=False)
        return payload
