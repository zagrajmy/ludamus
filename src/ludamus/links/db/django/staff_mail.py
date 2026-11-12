"""Staff answers to a case, mailed from the staff address as they were written."""

from __future__ import annotations

import logging
from email.utils import parseaddr

from django.conf import settings
from django.db import transaction

from ludamus.links.db.django.delivery import compose_as_written, send
from ludamus.pacts.staff_cases import StaffMailerProtocol

logger = logging.getLogger(__name__)


def staff_message_id(nonce: str) -> str:
    domain = parseaddr(settings.STAFF_EMAIL)[1].rpartition("@")[2] or "localhost"
    return f"<case-{nonce}@{domain}>"


class DjangoStaffMailer(StaffMailerProtocol):
    @staticmethod
    def send(*, to: str, subject: str, body: str, nonce: str) -> None:
        message = compose_as_written(
            to=to,
            subject=subject,
            body=body,
            from_email=settings.STAFF_EMAIL,
            message_id=staff_message_id(nonce),
        )

        def deliver() -> None:
            if send(message):
                logger.info("staff reply mailed: nonce=%s", nonce)

        transaction.on_commit(deliver, robust=True)
