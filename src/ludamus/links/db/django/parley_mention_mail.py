"""The email someone gets about chat mentions they have not read."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from django.conf import settings
from django.urls import reverse
from django.utils.text import Truncator
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.delivery import compose_mail, send
from ludamus.links.db.django.recipients import speaking_to
from ludamus.pacts.parley_mentions import ParleyMentionMailerProtocol

if TYPE_CHECKING:
    from ludamus.pacts.parley_mentions import ParleyMentionDigest

_MENTION = re.compile(r"<@(\d+)>")
_SNIPPET_LENGTH = 140


def _snippet(body: str, names: dict[str, str]) -> str:
    named = _MENTION.sub(lambda found: f"@{names.get(found[1]) or _('Someone')}", body)
    return Truncator(" ".join(named.split())).chars(_SNIPPET_LENGTH)


def _url(name: str, token: str) -> str:
    return absolute_url(
        reverse(name, kwargs={"token": token}), domain=str(settings.ROOT_DOMAIN)
    )


class DjangoParleyMentionMailer(ParleyMentionMailerProtocol):
    @staticmethod
    def send(digest: ParleyMentionDigest) -> bool:
        with speaking_to(digest.user_id) as recipient:
            count = sum(len(chat.lines) for chat in digest.chats)
            subject = ngettext(
                "Someone mentioned you in the chat",
                "You were mentioned %(count)s times in the chat",
                count,
            ) % {"count": count}
            home = absolute_url("/", domain=str(settings.ROOT_DOMAIN))
            parts = [_("Mentions of you that you have not read yet:")]
            for chat in digest.chats:
                lines = [
                    f"{line.author_name}: {_snippet(line.body, digest.names)}"
                    for line in chat.lines
                ]
                parts.append(
                    "\n".join([chat.title, *lines, f"{home}#parley:{chat.room_id}"])
                )
            footer = [
                _("You get this email because someone mentioned you in a chat."),
                _("Turn these emails off: %(url)s") % {
                    "url": _url("parley_mention_unsubscribe", digest.unsubscribe_token)
                },
            ]
            if address := settings.MAIL_POSTAL_ADDRESS:
                footer.append(address)
            body = "\n\n".join(parts) + "\n\n-- \n" + "\n".join(footer)
            confirm = _url(
                "parley_mention_unsubscribe_confirm", digest.unsubscribe_token
            )
            message = compose_mail(
                recipient,
                subject=subject,
                body=body,
                headers={
                    "List-Unsubscribe": f"<{confirm}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
            )
            return send(message)
