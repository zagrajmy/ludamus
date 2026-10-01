import email.policy

from django.urls import reverse

MAX_ICS_LINE_OCTETS = 75


def calendar_part(message):
    [(content, mimetype)] = [
        (content, mimetype)
        for content, mimetype in message.alternatives
        if mimetype.startswith("text/calendar")
    ]
    return content, mimetype


def wire_calendar_lines(message):
    # NOTE: prod's SMTP backend serialises with email.policy.SMTP; that is
    # what a receiving calendar parses.
    raw = message.message(policy=email.policy.SMTP).as_bytes()
    start = raw.index(b"BEGIN:VCALENDAR")
    end = raw.index(b"END:VCALENDAR") + len(b"END:VCALENDAR\r\n")
    return raw[start:end].split(b"\r\n")[:-1]


def rsvp(client, encounter):
    return client.post(
        reverse(
            "web:notice-board:encounter-rsvp",
            kwargs={"share_code": encounter.share_code},
        )
    )
