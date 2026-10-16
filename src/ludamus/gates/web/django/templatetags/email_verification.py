from email.utils import parseaddr
from urllib.parse import quote, urlencode

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def verification_mailbox(email: str) -> dict[str, str]:
    sender = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    gmail_url = ""
    if email.rpartition("@")[2].lower() == "gmail.com":
        query = f"in:anywhere from:{sender} to:{email}"
        account = urlencode({"authuser": email})
        search = quote(query, safe="")
        gmail_url = f"https://mail.google.com/mail/?{account}#search/{search}"
    return {"sender": sender, "gmail_url": gmail_url}
