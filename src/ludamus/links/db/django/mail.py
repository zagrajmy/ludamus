"""The one failure policy for mail that announces a committed change."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.mail import mailers
from django.db import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def send_after_commit(
    messages: Sequence[EmailMessage],
    *,
    label: str,
    still_wanted: Callable[[], bool] | None = None,
    on_failure: Callable[[], None] | None = None,
) -> None:
    """Send `messages` once the surrounding transaction commits.

    SMTP can't be un-sent, so mail waits for the real commit, and a failed
    send must not undo the change it announces: a failure is logged, never
    raised, and `on_failure` lets the caller re-arm what it marked as mailed.
    `still_wanted` re-checks, at send time, a consent that may have been
    withdrawn while the mail sat in the queue.
    """
    batch = list(messages)

    def _send() -> None:
        if still_wanted is not None and not still_wanted():
            logger.info("%s skipped: no longer wanted", label)
            return
        try:
            sent = mailers.default.send_messages(batch)
        except OSError:
            logger.exception("%s not delivered", label)
        else:
            if sent == len(batch):
                logger.info("%s sent (%d)", label, sent)
                return
            logger.warning(
                "%s: %d of %d not delivered", label, len(batch) - sent, len(batch)
            )
        if on_failure is not None:
            on_failure()

    transaction.on_commit(_send, robust=True)
