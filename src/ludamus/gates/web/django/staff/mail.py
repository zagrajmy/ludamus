"""Mail to the staff address, forwarded by the posta mail Worker.

posta posts each message raw, signed with an HMAC of a timestamp and the
body, so a replayed or altered message is refused. Mounted under ``/hooks/``,
which private spheres leave open: the Worker has no login.
"""

from __future__ import annotations

import email
import email.policy
import hmac
import logging
import time
from email.utils import parseaddr
from hashlib import sha256
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core.validators import validate_email
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import View

from ludamus.pacts.moderation import case_reference
from ludamus.pacts.staff_cases import CASE_EMAIL_LINE_MAX_LENGTH, InboundEmail

if TYPE_CHECKING:
    from email.message import MIMEPart

    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Posta-Signature"
SIGNATURE_TOLERANCE_SECONDS = 300
# NOTE: what `CaseEmail.address`, an EmailField, holds.
_ADDRESS_MAX_LENGTH = 254


def signature(*, secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, sha256
    ).hexdigest()


def _signed(header: str, *, secret: str, body: bytes, now: float) -> bool:
    fields = dict(
        part.strip().partition("=")[::2] for part in header.split(",") if "=" in part
    )
    try:
        timestamp = int(fields.get("t", ""))
    except ValueError:
        return False
    if abs(now - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    expected = signature(secret=secret, timestamp=timestamp, body=body)
    return hmac.compare_digest(fields.get("v1", ""), expected)


def _text(message: MIMEPart) -> str:
    if (part := message.get_body(preferencelist=("plain", "html"))) is None:
        return ""
    try:
        content: str = part.get_content()
    except LookupError, UnicodeError:
        # NOTE: senders name charsets Python lacks, such as "unknown-8bit".
        raw = part.get_payload(decode=True)
        content = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else ""
    return strip_tags(content) if part.get_content_type() == "text/html" else content


def _address(header: str) -> tuple[str, str]:
    name, address = parseaddr(header)
    try:
        validate_email(address)
    except ValidationError:
        return name, ""
    if len(address) > _ADDRESS_MAX_LENGTH:
        return name, ""
    return name, address.lower()


def parse_mail(raw: bytes) -> InboundEmail:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    name, address = _address(str(message.get("From", "")))
    message_id = str(message.get("Message-ID", "")).strip()
    if not message_id or len(message_id) > CASE_EMAIL_LINE_MAX_LENGTH:
        # NOTE: a mail without a usable one is still filed once, by its bytes.
        message_id = f"<{sha256(raw).hexdigest()}@posta>"
    return InboundEmail(
        message_id=message_id,
        from_address=address,
        from_name=name[:CASE_EMAIL_LINE_MAX_LENGTH],
        subject=" ".join(str(message.get("Subject", "")).split())[
            :CASE_EMAIL_LINE_MAX_LENGTH
        ],
        body=_text(message).strip(),
        attachments=[
            part.get_filename() or part.get_content_type()
            for part in message.iter_attachments()
        ],
    )


@method_decorator(csrf_exempt, name="dispatch")
class StaffMailHookView(View):
    """HMAC-signed webhook; CSRF does not apply (no cookie auth)."""

    request: RootRequest

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        if not (secret := settings.STAFF_MAIL_WEBHOOK_SECRET):
            raise Http404
        try:
            raw = request.body
        except RequestDataTooBig:
            logger.info("staff mail hook: message over the upload limit")
            return JsonResponse(
                {"error": "Message too large."},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if not _signed(
            request.headers.get(SIGNATURE_HEADER, ""),
            secret=secret,
            body=raw,
            now=time.time(),
        ):
            logger.warning("staff mail hook: signature refused")
            return JsonResponse(
                {"error": "Bad signature."}, status=HTTPStatus.UNAUTHORIZED
            )
        mail = parse_mail(raw)
        if not mail.from_address:
            logger.info("staff mail hook: no sender address")
            return JsonResponse(
                {"error": "No sender address."}, status=HTTPStatus.UNPROCESSABLE_ENTITY
            )
        receipt = request.services.staff_cases.receive_email(mail)
        return JsonResponse(
            {"outcome": receipt.outcome, "case": case_reference(receipt.case_id)}
        )
